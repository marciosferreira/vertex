"""
LangChain tools do scheduler — usam SQLite via db.get_db().
"""

import re as _re
from datetime import datetime
from typing import Optional

from langchain_core.tools import tool

from db import get_db
from .md_parser import calculate_next_run

_MIN_INTERVAL_MINUTES = 5


def _validate_frequency(frequency: str) -> str | None:
    """Retorna mensagem de erro se a frequência for inválida, None se OK."""
    if frequency == 'on_demand':
        return None
    m = _re.match(r'every_(\d+)m$', frequency)
    if m and int(m.group(1)) < _MIN_INTERVAL_MINUTES:
        return f"Intervalo mínimo permitido é {_MIN_INTERVAL_MINUTES} minutos. Use 'every_{_MIN_INTERVAL_MINUTES}m' ou maior."
    return None


_WEEKDAY_PT = {
    'monday': 'segunda', 'tuesday': 'terça', 'wednesday': 'quarta',
    'thursday': 'quinta', 'friday': 'sexta', 'saturday': 'sábado', 'sunday': 'domingo',
}


def _next_id() -> str:
    # Sequência monotônica — nunca regride, mesmo após deleção de tasks.
    with get_db() as conn:
        row = conn.execute(
            "UPDATE task_id_sequence SET next_id = next_id + 1 WHERE id = 1 RETURNING next_id - 1 AS cur"
        ).fetchone()
        conn.commit()
        return str(row["cur"]).zfill(3)


def _freq_label(task: dict) -> str:
    import re
    freq = task.get('frequency', '')
    time_str = task.get('time', '')
    if freq == 'on_demand':
        return 'sob demanda'
    m = re.match(r'every_(\d+)m', freq)
    if m:
        return f"a cada {m.group(1)} min"
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
            'active':  '✅ ativa',
            'draft':   '⏳ gerando código',
            'paused':  '⏸️ pausada',
            'error':   '❌ erro',
            'completed': '✔️ concluída',
        }.get(t.get('status', ''), t.get('status', ''))
        lines.append(f"**[{t['id']}]** {t.get('name', '?')}")
        lines.append(f"  Frequência : {_freq_label(t)}")
        if t.get('frequency') != 'on_demand':
            lines.append(f"  Próxima    : {t.get('next_run', 'N/A')}")
        lines.append(f"  Status     : {status_label}")
        if t.get('email'):
            lines.append(f"  Email      : {t['email']}")
        lines.append(f"  Descrição  : {t.get('description', '')}")
        lines.append("")
    return '\n'.join(lines)


def _push_artifacts(event_type: str, tokens: list[str], task_id: str) -> None:
    """Empurra artefatos diretamente para o stream SSE do chat."""
    try:
        from agent_multi import _push_event, _current_session
        session = _current_session.get()
        for token in tokens:
            _push_event(session, {"type": event_type, "token": token, "task_id": task_id})
    except Exception:
        pass  # silencioso — não quebra a tool se o stream não estiver ativo


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _current_user_id() -> str | None:
    try:
        from agent_multi import _current_session
        sid = _current_session.get("")
        return sid[:36] if sid else None
    except Exception:
        return None


def _all_tasks(user_id: str | None = None) -> list[dict]:
    with get_db() as conn:
        if user_id:
            rows = conn.execute("SELECT * FROM scheduled_tasks WHERE user_id=? ORDER BY id", (user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM scheduled_tasks ORDER BY id").fetchall()
    return [_row_to_dict(r) for r in rows]


@tool
def schedule_task(
    name: str,
    description: str,
    frequency: str,
    time: Optional[str] = None,
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
                   "every_Xm" (ex: "every_2m") | "every_Xh" | "every_Xd" |
                   "on_demand" (sem agendamento — executa só quando o usuário clicar ▶ no painel)
        time: Hora no formato "HH:MM" (ex: "08:00"). Se omitido, usa a hora
              atual como ponto de partida. Ignorado se frequency="on_demand".
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
    err = _validate_frequency(frequency)
    if err:
        return err

    task_id = _next_id()
    user_id = _current_user_id()
    next_run = calculate_next_run(frequency, time, weekday, day)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        conn.execute(
            """INSERT INTO scheduled_tasks
               (id, name, description, instructions, frequency, time, weekday,
                day, email, status, next_run, last_run, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,'draft',?,NULL,?,?)""",
            (task_id, name, description, instructions, frequency, time,
             weekday, day, email, next_run, now, user_id),
        )
        conn.commit()

    tasks = _all_tasks(user_id)
    if frequency == 'on_demand':
        schedule_info = "Execute quando quiser clicando em ▶ no painel de tarefas."
    else:
        schedule_info = f"Próxima execução agendada: {next_run}"
    return (
        f"Tarefa **[{task_id}]** criada (aguardando código). {schedule_info}\n\n"
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

    uid = _current_user_id()
    tasks = _all_tasks(uid)
    return (
        f"Instruções da tarefa **[{task_id}]** definidas. Status: ✅ ativa.\n\n"
        + _format_list(tasks)
    )


@tool
def list_scheduled_tasks() -> str:
    """Lista todas as tarefas agendadas com status, frequência e descrição."""
    return _format_list(_all_tasks(_current_user_id()))


@tool
def get_task_instructions(task_id: str) -> str:
    """Retorna as instructions de execução de uma tarefa (passo a passo + código).

    Use antes de editar uma tarefa para obter o contexto atual do que ela executa.

    Args:
        task_id: ID da tarefa (ex: "001").
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT name, instructions FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    if not row:
        return f"Tarefa '{task_id}' não encontrada."
    instructions = row['instructions'] or '(sem instructions definidas)'
    return f"**Tarefa [{task_id}] — {row['name']}**\n\nInstruções atuais:\n{instructions}"


@tool
def toggle_pause_task(task_id: str) -> str:
    """Pausa uma tarefa ativa ou retoma uma tarefa pausada.

    Não afeta tasks em execução, concluídas ou com erro.

    Args:
        task_id: ID da tarefa (ex: "001"). Use list_scheduled_tasks para ver os IDs.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT name, status FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            ids = [r['id'] for r in conn.execute("SELECT id FROM scheduled_tasks").fetchall()]
            return f"Tarefa '{task_id}' não encontrada. IDs existentes: {ids}"
        current = row["status"]
        if current not in ("active", "paused"):
            return f"Não é possível pausar/retomar tarefa com status '{current}'."
        new_status = "paused" if current == "active" else "active"
        conn.execute("UPDATE scheduled_tasks SET status=? WHERE id=?", (new_status, task_id))
        conn.commit()

    uid = _current_user_id()
    action = "pausada" if new_status == "paused" else "retomada"
    return (
        f"Tarefa **[{task_id}]** {action}.\n\n"
        + _format_list(_all_tasks(uid))
    )


@tool
def delete_scheduled_task(task_id: str) -> str:
    """Remove uma tarefa agendada pelo ID.

    Args:
        task_id: ID da tarefa (ex: "001"). Use list_scheduled_tasks para ver os IDs.
    """
    uid = _current_user_id()
    with get_db() as conn:
        row = conn.execute(
            "SELECT name FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            ids = [r['id'] for r in conn.execute("SELECT id FROM scheduled_tasks WHERE user_id=?", (uid,)).fetchall()]
            return f"Tarefa '{task_id}' não encontrada. IDs existentes: {ids}"
        name = row['name']
        conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.execute("DELETE FROM task_runs WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM task_code_versions WHERE task_id = ?", (task_id,))
        conn.commit()

    return (
        f"Tarefa **[{task_id}]** ({name}) removida.\n\n"
        + _format_list(_all_tasks(uid))
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
            err = _validate_frequency(frequency)
            if err:
                return err
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

    uid = _current_user_id()
    return (
        f"Tarefa **[{task_id}]** atualizada. Campos: {', '.join(updates)}\n\n"
        + _format_list(_all_tasks(uid))
    )


@tool
def get_task_code(task_id: str) -> str:
    """Retorna o task_code Python armazenado de uma tarefa.

    Use este tool antes de editar o código para obter a versão atual.

    Args:
        task_id: ID da tarefa (ex: "001").
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT name, task_code FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    if not row:
        return f"Tarefa '{task_id}' não encontrada."
    if not row['task_code']:
        return f"Tarefa [{task_id}] não possui task_code. Usa instruções LLM."
    return f"**Tarefa [{task_id}] — {row['name']}**\n\nCódigo atual:\n```python\n{row['task_code']}\n```"


@tool
def test_task_code(task_id: str, code: str, from_date: str = "", to_date: str = "") -> str:
    """Compila e executa um trecho de task_code para validação antes de salvar.

    O código deve definir `def run(from_date, to_date, ctx)` e retornar token(s).
    Executa em sandbox com builtins restritos + matplotlib/numpy/pandas/openpyxl.

    Args:
        task_id: ID da tarefa (usado apenas para nomear a sessão de teste).
        code: Código Python completo a testar.
        from_date: Data inicial no formato YYYY-MM-DD (padrão: 7 dias atrás).
        to_date: Data final no formato YYYY-MM-DD (padrão: hoje).
    """
    from .runner import run_task_code, default_test_range, TaskCodeError
    from datetime import datetime

    if not from_date or not to_date:
        from_date, to_date = default_test_range()

    session_id = f"test_{task_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        tokens, ctx = run_task_code(code, from_date, to_date, session_id, user_id=_current_user_id(), is_test=True)
        _push_artifacts("artifact_preview", tokens, task_id)

        alert_lines = []
        for a in ctx.test_alerts():
            parts = [f"  🔔 {a['message']}"]
            if a.get('value') is not None:
                parts.append(f"valor={a['value']}")
            if a.get('threshold') is not None:
                parts.append(f"threshold={a['threshold']}")
            alert_lines.append(" | ".join(parts))

        alert_section = (
            "\n\n**Notificações que seriam disparadas:**\n" + "\n".join(alert_lines)
            if alert_lines else ""
        )

        return (
            f"✅ **Teste bem-sucedido!** Período: {from_date} → {to_date}\n"
            f"Artefatos enviados para o chat: {', '.join(tokens)}"
            f"{alert_section}"
        )
    except TaskCodeError as e:
        return f"❌ **Erro no código:**\n```\n{e}\n```\nCorreja e teste novamente antes de salvar."
    except Exception as e:
        return f"❌ **Erro inesperado:**\n```\n{e}\n```"


@tool
def save_task_code(task_id: str, code: str) -> str:
    """Salva task_code Python em uma tarefa, criando versão histórica para rollback.

    Após salvar, a tarefa executa o código diretamente (modo determinístico),
    sem passar pelo LLM. Use test_task_code antes de salvar.

    Args:
        task_id: ID da tarefa (ex: "001").
        code: Código Python completo com `def run(from_date, to_date, ctx)`.
    """
    from datetime import datetime

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        row = conn.execute(
            "SELECT name, task_code FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return f"Tarefa '{task_id}' não encontrada."

        # Arquiva versão anterior se existir
        if row['task_code']:
            ver_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS nxt FROM task_code_versions WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            version = ver_row['nxt']
            conn.execute(
                "INSERT INTO task_code_versions (task_id, version, code, created_at) VALUES (?, ?, ?, ?)",
                (task_id, version, row['task_code'], now),
            )

        conn.execute(
            "UPDATE scheduled_tasks SET task_code = ?, status = 'active' WHERE id = ?",
            (code, task_id),
        )
        conn.commit()

    # Promove artifacts do teste para a sessão real (aparecem no painel de artifacts)
    try:
        from agent_multi import _current_session
        import chart_store
        chart_store.promote_test_artifacts(task_id, _current_session.get())
    except Exception:
        pass

    # Notifica o chat que o código foi persistido
    _push_artifacts("artifact_saved", [], task_id)
    return (
        f"✅ **task_code salvo** na tarefa **[{task_id}]** ({row['name']}).\n"
        "A próxima execução usará este código diretamente (modo determinístico).\n"
        "Use `get_task_code_versions` para ver o histórico ou `restore_task_code_version` para reverter."
    )


@tool
def get_task_code_versions(task_id: str) -> str:
    """Lista as versões históricas do task_code de uma tarefa (para rollback).

    Args:
        task_id: ID da tarefa (ex: "001").
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT version, created_at FROM task_code_versions WHERE task_id = ? ORDER BY version DESC",
            (task_id,)
        ).fetchall()
    if not rows:
        return f"Tarefa [{task_id}] não possui versões arquivadas."
    lines = [f"**Versões do task_code — Tarefa [{task_id}]:**\n"]
    for r in rows:
        lines.append(f"  v{r['version']} — salva em {r['created_at']}")
    lines.append("\nUse `restore_task_code_version` para restaurar uma versão.")
    return '\n'.join(lines)


@tool
def restore_task_code_version(task_id: str, version: int) -> str:
    """Restaura uma versão anterior do task_code de uma tarefa.

    O código atual é arquivado como nova versão antes de restaurar.

    Args:
        task_id: ID da tarefa (ex: "001").
        version: Número da versão a restaurar (use get_task_code_versions para listar).
    """
    from datetime import datetime

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        ver_row = conn.execute(
            "SELECT code FROM task_code_versions WHERE task_id = ? AND version = ?",
            (task_id, version)
        ).fetchone()
        if not ver_row:
            return f"Versão {version} não encontrada para a tarefa [{task_id}]."

        task_row = conn.execute(
            "SELECT name, task_code FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not task_row:
            return f"Tarefa '{task_id}' não encontrada."

        # Arquiva versão atual antes de restaurar
        if task_row['task_code']:
            new_ver = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS nxt FROM task_code_versions WHERE task_id = ?",
                (task_id,)
            ).fetchone()['nxt']
            conn.execute(
                "INSERT INTO task_code_versions (task_id, version, code, created_at) VALUES (?, ?, ?, ?)",
                (task_id, new_ver, task_row['task_code'], now),
            )

        conn.execute(
            "UPDATE scheduled_tasks SET task_code = ? WHERE id = ?",
            (ver_row['code'], task_id),
        )
        conn.commit()

    return (
        f"✅ **Versão {version} restaurada** na tarefa **[{task_id}]** ({task_row['name']}).\n"
        "O código anterior foi arquivado como nova versão."
    )
