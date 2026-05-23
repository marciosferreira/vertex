"""
Daemon do scheduler — lê scheduled_tasks do SQLite, verifica horários e
dispara execuções em thread separada. Zero LLM neste módulo.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from db import get_db
from .md_parser import calculate_next_run
from .runner import run_task_code, TaskCodeError

logger = logging.getLogger(__name__)

import os

REPORTS_DIR = Path(__file__).parent.parent / "reports"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

_CHECK_INTERVAL_SECONDS = 60
_TASK_TIMEOUT_SECONDS   = 600          # 10 min — mata execuções travadas
_RETRY_BACKOFF_MINUTES  = [5, 15, 60]  # espera entre tentativas (1ª, 2ª, 3ª)

_PDF_TOKEN = re.compile(r'\[pdf:([a-f0-9\-]{36})\]')


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


def _date_range_for_task(task: dict) -> tuple[str, str]:
    """Calcula from_date/to_date com base na frequência da tarefa.

    Garante que o task_code sempre receba o período correto para cada
    frequência, sem depender de datas hardcoded no código da tarefa.
    """
    import re
    today = datetime.now().date()
    freq  = task.get('frequency', 'daily')

    if freq == 'daily':
        delta = 1
    elif freq == 'weekly':
        delta = 7
    elif freq == 'monthly':
        delta = 30
    elif freq in ('once', 'on_demand'):
        delta = 7
    else:
        m = re.match(r'every_(\d+)d', freq)
        if m:
            delta = int(m.group(1))
        elif re.match(r'every_(\d+)[hm]', freq):
            delta = 1  # horas ou minutos → janela de hoje
        else:
            delta = 7

    from_date = (today - timedelta(days=delta)).isoformat()
    to_date   = today.isoformat()
    return from_date, to_date



def _start_run(task_id: str, started_at: str) -> int:
    """Insere uma linha em task_runs e retorna o run_id."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO task_runs (task_id, started_at, status) VALUES (?, ?, 'running')",
            (task_id, started_at),
        )
        conn.commit()
        return cur.lastrowid


def _finish_run(run_id: int, status: str, output: str = None, error: str = None) -> None:
    ended_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        conn.execute(
            "UPDATE task_runs SET ended_at=?, status=?, output=?, error=? WHERE id=?",
            (ended_at, status, output, error, run_id),
        )
        conn.commit()


def _execute_task(task: dict) -> None:
    now      = datetime.now()
    task_id  = task['id']
    now_str  = now.strftime('%Y-%m-%d %H:%M:%S')

    # ── 1. Marca como running (impede execução dupla) ────────────────────────
    with get_db() as conn:
        updated = conn.execute(
            "UPDATE scheduled_tasks SET status='running' WHERE id=? AND status='active'",
            (task_id,),
        ).rowcount
        conn.commit()

    if updated == 0:
        # Outra thread já pegou esta task (ou foi pausada/cancelada entre o
        # SELECT e o UPDATE). Abandona silenciosamente.
        logger.info("[daemon] Task %s ignorada (já em running ou inativa)", task_id)
        return

    run_id = _start_run(task_id, now_str)
    logger.info("[daemon] Iniciando task %s '%s' (run #%d)", task_id, task.get('name'), run_id)

    # ── 2. Executa com timeout ───────────────────────────────────────────────
    try:
        import concurrent.futures
        session_id = f"daemon_{task_id}_{now.strftime('%Y%m%d%H%M')}"

        if not task.get("task_code"):
            msg = "Tarefa sem task_code — salve o código via chat antes de ativar."
            logger.warning("[daemon] Task %s ignorada: %s", task_id, msg)
            _finish_run(run_id, 'error', error=msg)
            _handle_retry(task, now_str, msg)
            return

        from_date, to_date = _date_range_for_task(task)

        user_id = task.get("user_id")

        def _run_code():
            tokens = run_task_code(task["task_code"], from_date, to_date, session_id, user_id=user_id)
            return " ".join(tokens)

        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = ex.submit(_run_code)
        try:
            result = future.result(timeout=_TASK_TIMEOUT_SECONDS)
        finally:
            # shutdown(wait=False) evita bloquear o daemon enquanto a thread
            # travada termina — sem isso o `with` esperaria eternamente
            ex.shutdown(wait=False, cancel_futures=True)

        logger.info("[daemon] Task %s concluída (run #%d)", task_id, run_id)

        folder = _save_report(task, result, now)
        logger.info("[daemon] Relatório salvo em %s", folder)

        _finish_run(run_id, 'success', output=result[:4000])

        # ── 3a. Sucesso: agenda próxima execução ─────────────────────────────
        last_run = now_str
        if task.get('frequency') == 'once':
            with get_db() as conn:
                conn.execute(
                    "UPDATE scheduled_tasks SET last_run=?, status='completed', retry_count=0 WHERE id=?",
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
                    "UPDATE scheduled_tasks SET last_run=?, next_run=?, status='active', retry_count=0 WHERE id=?",
                    (last_run, next_run, task_id),
                )
                conn.commit()

    except concurrent.futures.TimeoutError:
        msg = f"Timeout após {_TASK_TIMEOUT_SECONDS}s"
        logger.error("[daemon] Task %s excedeu timeout de %ds (run #%d)", task_id, _TASK_TIMEOUT_SECONDS, run_id)
        _finish_run(run_id, 'error', error=msg)
        _handle_retry(task, now_str, msg)

    except TaskCodeError as exc:
        logger.error("[daemon] Erro no task_code da task %s (run #%d): %s", task_id, run_id, exc)
        _finish_run(run_id, 'error', error=str(exc))
        _handle_retry(task, now_str, str(exc))

    except Exception as exc:
        logger.exception("[daemon] Falha na task %s (run #%d)", task_id, run_id)
        _finish_run(run_id, 'error', error=str(exc))
        _handle_retry(task, now_str, str(exc))


def _handle_retry(task: dict, last_run: str, error_msg: str) -> None:
    """Incrementa retry_count. Se ainda há tentativas, agenda reexecução com backoff.
    Caso contrário, marca a task como 'error' para revisão manual."""
    task_id     = task['id']
    retry_count = task.get('retry_count', 0) + 1
    max_retries = task.get('max_retries', 3)

    if retry_count <= max_retries:
        backoff_min = _RETRY_BACKOFF_MINUTES[min(retry_count - 1, len(_RETRY_BACKOFF_MINUTES) - 1)]
        next_run    = (datetime.now() + timedelta(minutes=backoff_min)).strftime('%Y-%m-%d %H:%M:%S')
        logger.warning(
            "[daemon] Task %s tentativa %d/%d — reagendada para %s (backoff %dmin)",
            task_id, retry_count, max_retries, next_run, backoff_min,
        )
        with get_db() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET status='active', retry_count=?, next_run=?, last_run=? WHERE id=?",
                (retry_count, next_run, last_run, task_id),
            )
            conn.commit()
    else:
        logger.error(
            "[daemon] Task %s esgotou %d tentativas. Status: error. Erro: %s",
            task_id, max_retries, error_msg,
        )
        with get_db() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET status='error', retry_count=?, last_run=? WHERE id=?",
                (retry_count, last_run, task_id),
            )
            conn.commit()


def check_due_tasks() -> None:
    with get_db() as conn:
        rows = conn.execute(
            # 'running' é excluído — evita execução dupla em tasks lentas
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
