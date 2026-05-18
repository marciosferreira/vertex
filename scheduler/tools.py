"""
LangChain tools do scheduler — usam SQLite via db.get_db().
"""

from datetime import datetime
from typing import Optional

from langchain_core.tools import tool

from db import get_db
from .md_parser import calculate_next_run


_WEEKDAY_PT = {
    'monday': 'segunda', 'tuesday': 'terça', 'wednesday': 'quarta',
    'thursday': 'quinta', 'friday': 'sexta', 'saturday': 'sábado', 'sunday': 'domingo',
}


def _next_id() -> str:
    with get_db() as conn:
        rows = conn.execute("SELECT id FROM scheduled_tasks").fetchall()
        used = [int(r['id']) for r in rows]
        return str((max(used, default=0) + 1)).zfill(3)


def _freq_label(task: dict) -> str:
    import re
    freq = task.get('frequency', '')
    time_str = task.get('time', '')
    if re.match(r'every_(\d+)m', freq):
        return f"a cada {re.match(r'every_(\d+)m', freq).group(1)} min"
    if freq == 'once':
        return f"única vez em {task.get('next_run', '?')}"
    if freq == 'daily':
        return f"diária às {time_str}"
    if freq == 'weekly':
        wd = _WEEKDAY_PT.get(task.get('weekday', ''), task.get('weekday', ''))
        return f"semanal ({wd}) às {time_str}"
    if freq == 'monthly':
        return f"mensal (dia {task.get('day', '?')}) às {time_str}"
    m = re.match(r'every_(\d+)h', freq)
    if m:
        return f"a cada {m.group(1)}h"
    m = re.match(r'every_(\d+)d', freq)
    if m:
        return f"a cada {m.group(1)} dias"
    return freq


def _format_list(tasks: list[dict]) -> str:
    active = [t for t in tasks if t.get('status') not in ('completed', 'cancelled')]
    if not active:
        return "Nenhuma tarefa agendada no momento."
    lines = [f"**{len(active)} tarefa(s) agendada(s):**\n"]
    for t in active:
        status_label = {
            'active': '✅ ativa',
            'paused': '⏸️ pausada',
            'error': '❌ erro',
            'completed': '✔️ concluída',
        }.get(t.get('status', ''), t.get('status', ''))
        lines.append(f"**[{t['id']}]** {t.get('name', '?')}")
        lines.append(f"  Frequência : {_freq_label(t)}")
        lines.append(f"  Próxima    : {t.get('next_run', 'N/A')}")
        lines.append(f"  Status     : {status_label}")
        if t.get('email'):
            lines.append(f"  Email      : {t['email']}")
        lines.append(f"  Descrição  : {t.get('description', '')}")
        lines.append("")
    return '\n'.join(lines)


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _all_tasks() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM scheduled_tasks ORDER BY id").fetchall()
    return [_row_to_dict(r) for r in rows]


@tool
def schedule_task(
    name: str,
    description: str,
    frequency: str,
    time: str,
    instructions: Optional[str] = None,
    email: Optional[str] = None,
    weekday: Optional[str] = None,
    day: Optional[str] = None,
) -> str:
    """Agenda uma tarefa recorrente ou pontual.

    Args:
        name: Nome curto da tarefa (ex: "Relatório Semanal de Produção").
        description: Resumo legível do que a tarefa faz — aparece na listagem
                     para o usuário. Ex: "Gera relatório semanal de OEE por
                     linha toda segunda às 8h e envia por email."
        frequency: Frequência de execução. Valores aceitos:
                   "once" | "daily" | "weekly" | "monthly" |
                   "every_Xm" (ex: "every_2m") | "every_Xh" | "every_Xd"
        time: Hora no formato "HH:MM" (ex: "08:00").
        instructions: Passo a passo detalhado de execução, incluindo os
                      trechos de código Python validados. Se fornecido, a
                      tarefa fica ativa imediatamente. Se omitido, fica com
                      status "pending_approval" até ser definido via
                      set_task_instructions.
        email: Endereço de email para envio do relatório (opcional).
        weekday: Obrigatório se frequency="weekly".
                 Valores: "monday" | "tuesday" | "wednesday" | "thursday" |
                          "friday" | "saturday" | "sunday"
        day: Obrigatório se frequency="monthly". Dia do mês (ex: "1", "15").
    """
    task_id = _next_id()
    next_run = calculate_next_run(frequency, time, weekday, day)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        conn.execute(
            """INSERT INTO scheduled_tasks
               (id, name, description, instructions, frequency, time, weekday,
                day, email, status, next_run, last_run, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,'active',?,NULL,?)""",
            (task_id, name, description, instructions, frequency, time,
             weekday, day, email, next_run, now),
        )
        conn.commit()

    tasks = _all_tasks()
    return (
        f"Tarefa **[{task_id}]** criada e ativa. Próxima execução agendada: {next_run}\n\n"
        + _format_list(tasks)
        + "\nPara remover tarefa redundante: **delete task [ID]**"
    )


@tool
def set_task_instructions(task_id: str, instructions: str) -> str:
    """Define ou substitui as instruções de execução de uma tarefa.

    As instruções devem conter o passo a passo e os trechos de código Python
    validados. Ao definir as instruções, a tarefa é ativada automaticamente.

    Args:
        task_id: ID da tarefa (ex: "001").
        instructions: Passo a passo completo com código Python validado.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return f"Tarefa '{task_id}' não encontrada."
        conn.execute(
            "UPDATE scheduled_tasks SET instructions = ?, status = 'active' WHERE id = ?",
            (instructions, task_id),
        )
        conn.commit()

    tasks = _all_tasks()
    return (
        f"Instruções da tarefa **[{task_id}]** definidas. Status: ✅ ativa.\n\n"
        + _format_list(tasks)
    )


@tool
def list_scheduled_tasks() -> str:
    """Lista todas as tarefas agendadas com status, frequência e descrição."""
    return _format_list(_all_tasks())


@tool
def delete_scheduled_task(task_id: str) -> str:
    """Remove uma tarefa agendada pelo ID.

    Args:
        task_id: ID da tarefa (ex: "001"). Use list_scheduled_tasks para ver os IDs.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT name FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            ids = [r['id'] for r in conn.execute("SELECT id FROM scheduled_tasks").fetchall()]
            return f"Tarefa '{task_id}' não encontrada. IDs existentes: {ids}"
        name = row['name']
        conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.commit()

    tasks = _all_tasks()
    return (
        f"Tarefa **[{task_id}]** ({name}) removida.\n\n"
        + _format_list(tasks)
    )


@tool
def update_scheduled_task(
    task_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    frequency: Optional[str] = None,
    time: Optional[str] = None,
    email: Optional[str] = None,
    weekday: Optional[str] = None,
    day: Optional[str] = None,
) -> str:
    """Edita campos de uma tarefa existente. Apenas os campos fornecidos são alterados.

    Se frequency, time, weekday ou day forem alterados, next_run é recalculado.
    Para editar as instruções de execução use set_task_instructions.

    Args:
        task_id: ID da tarefa (ex: "001").
        name: Novo nome curto.
        description: Nova descrição legível (o que aparece na listagem).
        frequency: Nova frequência.
        time: Novo horário "HH:MM".
        email: Novo email (string vazia para remover).
        weekday: Novo dia da semana (se frequency="weekly").
        day: Novo dia do mês (se frequency="monthly").
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            ids = [r['id'] for r in conn.execute("SELECT id FROM scheduled_tasks").fetchall()]
            return f"Tarefa '{task_id}' não encontrada. IDs existentes: {ids}"

        task = _row_to_dict(row)
        updates: dict = {}
        if name is not None:
            updates['name'] = name
        if description is not None:
            updates['description'] = description
        if email is not None:
            updates['email'] = email or None
        if weekday is not None:
            updates['weekday'] = weekday
        if day is not None:
            updates['day'] = day
        if frequency is not None:
            updates['frequency'] = frequency
        if time is not None:
            updates['time'] = time

        sched_changed = any(p is not None for p in (frequency, time, weekday, day))
        if sched_changed:
            updates['next_run'] = calculate_next_run(
                updates.get('frequency', task.get('frequency', 'daily')),
                updates.get('time', task.get('time', '08:00')),
                updates.get('weekday', task.get('weekday')),
                updates.get('day', task.get('day')),
            )

        if not updates:
            return "Nenhum campo fornecido para atualizar."

        set_clause = ', '.join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE scheduled_tasks SET {set_clause} WHERE id = ?",
            (*updates.values(), task_id),
        )
        conn.commit()

    tasks = _all_tasks()
    return (
        f"Tarefa **[{task_id}]** atualizada. Campos: {', '.join(updates)}\n\n"
        + _format_list(tasks)
    )
