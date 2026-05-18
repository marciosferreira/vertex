"""
Daemon do scheduler — lê scheduled_tasks do SQLite, verifica horários e
dispara execuções em thread separada. Zero LLM neste módulo.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from db import get_db
from .md_parser import calculate_next_run

logger = logging.getLogger(__name__)

import os

REPORTS_DIR = Path(__file__).parent.parent / "reports"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

_PDF_TOKEN = re.compile(r'\[pdf:([a-f0-9\-]{36})\]')

_CHECK_INTERVAL_SECONDS = 120


def _resolve_pdf_links(content: str) -> str:
    return _PDF_TOKEN.sub(
        lambda m: f"[📄 Abrir relatório PDF]({BACKEND_URL}/pdf/{m.group(1)})",
        content,
    )


def _save_report(task: dict, content: str, now: datetime) -> Path:
    safe_name = re.sub(r'[^\w\-]', '_', task.get('name', 'report'))[:30].strip('_')
    folder_name = f"{task['id']}_{safe_name}_{now.strftime('%Y-%m-%d_%H%M')}"
    folder = REPORTS_DIR / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    pdf_ids = _PDF_TOKEN.findall(content)
    content_with_links = _resolve_pdf_links(content)
    (folder / 'content.md').write_text(content_with_links, encoding='utf-8')

    pdf_urls = [f"{BACKEND_URL}/pdf/{pid}" for pid in pdf_ids]
    metadata = {
        'task_id': task['id'],
        'task_name': task.get('name'),
        'run_at': now.isoformat(),
        'status': 'pending_send',
        'pdf_urls': pdf_urls,
        'email': {
            'to': task.get('email'),
            'subject': f"{task.get('name')} — {now.strftime('%Y-%m-%d %H:%M')}",
            'body': f"Segue em anexo o relatório: {task.get('name')}.",
            'attachments': pdf_urls,
        } if task.get('email') else None,
        'schedule': {
            'frequency': task.get('frequency'),
            'weekday': task.get('weekday'),
            'day': task.get('day'),
            'time': task.get('time'),
        },
    }
    (folder / 'metadata.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return folder


def _build_prompt(task: dict, now: datetime) -> str:
    ts = now.strftime('%d/%m/%Y %H:%M')
    header = (
        f"[EXECUÇÃO AUTOMÁTICA — {ts}]\n"
        "Você DEVE obrigatoriamente: (1) chamar consultar_analista para buscar os dados, "
        "(2) chamar gerar_pdf com toda a análise e gráficos gerados. "
        "NÃO responda com texto puro. Use as tools.\n\n"
    )
    footer = (
        "\n\nGere o PDF agora com gerar_pdf e retorne o token [pdf:uuid] na resposta."
    )

    if task.get('instructions'):
        return (
            header
            + "Siga exatamente as instruções abaixo, adaptando apenas datas para o período atual:\n\n"
            + task['instructions']
            + footer
        )

    return header + task.get('description', '') + footer


def _execute_task(task: dict) -> None:
    from agent_multi import invoke_multi_agent

    now = datetime.now()
    task_id = task['id']
    logger.info("[daemon] Executando task %s: %s", task_id, task.get('name'))

    try:
        session_id = f"daemon_{task_id}_{now.strftime('%Y%m%d%H%M')}"
        prompt = _build_prompt(task, now)
        result = invoke_multi_agent(prompt, session_id)
        logger.info("[daemon] Resultado task %s (primeiros 300 chars): %s", task_id, result[:300])

        folder = _save_report(task, result, now)
        logger.info("[daemon] Relatório salvo em %s", folder)

        last_run = now.strftime('%Y-%m-%d %H:%M:%S')
        if task.get('frequency') == 'once':
            with get_db() as conn:
                conn.execute(
                    "UPDATE scheduled_tasks SET last_run = ?, status = 'completed' WHERE id = ?",
                    (last_run, task_id),
                )
                conn.commit()
        else:
            next_run = calculate_next_run(
                task.get('frequency', 'daily'),
                task.get('time', '08:00'),
                task.get('weekday'),
                task.get('day'),
            )
            with get_db() as conn:
                conn.execute(
                    "UPDATE scheduled_tasks SET last_run = ?, next_run = ? WHERE id = ?",
                    (last_run, next_run, task_id),
                )
                conn.commit()

    except Exception:
        logger.exception("[daemon] Falha ao executar task %s", task_id)
        with get_db() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET status = 'error' WHERE id = ?",
                (task_id,),
            )
            conn.commit()


def check_due_tasks() -> None:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'active'"
        ).fetchall()

    now = datetime.now()
    for row in rows:
        task = dict(row)
        next_run_str = task.get('next_run')
        if not next_run_str:
            continue
        try:
            next_run = datetime.strptime(next_run_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        if next_run > now:
            continue
        _execute_task(task)


async def scheduler_loop() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    logger.info("[daemon] Scheduler iniciado — intervalo: %ds", _CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.to_thread(check_due_tasks)
        except Exception:
            logger.exception("[daemon] Erro no loop do scheduler")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
