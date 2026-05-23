"""
MFG Control — Backend FastAPI
==============================
Rodar:
    python -m uvicorn main:app --reload

Docs automáticas:
    http://localhost:8000/docs

Filosofia da API
----------------
Todos os endpoints de dados aceitam os mesmos filtros opcionais:
  from=YYYY-MM-DD  to=YYYY-MM-DD  shift=A|B|C  line=1|2|3|4

Isso permite compor qualquer consulta chamando um ou mais endpoints
e cruzando os resultados pelo campo `date`. Exemplo:

  GET /production?from=2026-05-01&to=2026-05-15&line=1
  GET /defects?from=2026-05-01&to=2026-05-15&line=1&category=Tela (display)

  → defect_rate por dia = defects[i].count / production[i].produced
"""

import asyncio
import logging
import os
import re
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from db import get_db, init_db, migrate_db, shift_dates_to_today

try:
    from dotenv import load_dotenv
    _VERTEX_AVAILABLE = True
except ImportError:
    _VERTEX_AVAILABLE = False

import json
import threading
from sse_starlette.sse import EventSourceResponse
from agent_multi import init_multi_agent, invoke_multi_agent, is_multi_agent_ready, stream_multi_agent, set_chart_snapshot, ns_cleanup_loop
from scheduler.daemon import scheduler_loop, _execute_task
import chart_store as cs

_CHART_RE = re.compile(r'\[chart:([a-f0-9\-]{36})\]')
_PDF_RE   = re.compile(r'\[pdf:([a-f0-9\-]{36})\]')
_EXCEL_RE = re.compile(r'\[excel:([a-f0-9\-]{36})\]')

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def _embed_charts(text: str) -> str:
    def _chart(m: re.Match) -> str:
        chart_id = m.group(1)
        if not cs.get_chart_b64(chart_id):
            return "[gráfico indisponível]"
        return f"![grafico](/chart/{chart_id})"

    def _pdf(m: re.Match) -> str:
        pdf_id = m.group(1)
        row = cs.get_pdf(pdf_id)
        if not row:
            return "[PDF indisponível]"
        _, filename = row
        return f"[📥 {filename}](/pdf/{pdf_id})"

    def _excel(m: re.Match) -> str:
        excel_id = m.group(1)
        row = cs.get_excel(excel_id)
        if not row:
            return "[Excel indisponível]"
        _, filename = row
        return f"[📥 {filename}](/excel/{excel_id})"

    text = _CHART_RE.sub(_chart, text)
    text = _PDF_RE.sub(_pdf, text)
    text = _EXCEL_RE.sub(_excel, text)
    return text


def _load_credentials():
    """Carrega credenciais Google como objeto, a partir de env var (base64) ou arquivo local."""
    import base64
    import json as _json
    from google.oauth2 import service_account

    SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

    b64 = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if b64:
        info = _json.loads(base64.b64decode(b64))
        logger.info("Credenciais Google carregadas via GOOGLE_CREDENTIALS_JSON")
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    creds_path = Path(__file__).parent / "credentials.json"
    if creds_path.exists():
        logger.info("Credenciais Google carregadas via credentials.json local")
        return service_account.Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)

    return None


def _init_vertex():
    if not _VERTEX_AVAILABLE:
        logger.warning("python-dotenv não instalado — chat IA desabilitado")
        return
    try:
        load_dotenv()
        project    = os.getenv("PROJECT_ID")
        location   = os.getenv("LOCATION", "us-central1")
        model_name = os.getenv("MODEL_NAME", "gemini-2.5-flash")
        if not project:
            logger.warning("PROJECT_ID não definido — chat IA desabilitado")
            return
        credentials = _load_credentials()
        init_multi_agent(project=project, location=location, model_name=model_name, credentials=credentials)
    except Exception:
        logger.warning("Falha ao inicializar Vertex AI:\n%s", traceback.format_exc())

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="MFG Control API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _error_body(status: int, exc_type: str, message: str, path: str) -> dict:
    return {"error": True, "status": status, "type": exc_type, "message": message, "path": path}


@app.exception_handler(Exception)
async def handler_500(request: Request, exc: Exception):
    logger.error("500 %s\n%s", request.url, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content=_error_body(500, type(exc).__name__, str(exc), str(request.url.path)),
    )


@app.exception_handler(404)
async def handler_404(request: Request, _: Exception):
    return JSONResponse(
        status_code=404,
        content=_error_body(404, "NotFound", f"Endpoint não encontrado: {request.url.path}", str(request.url.path)),
    )


@app.exception_handler(422)
async def handler_422(request: Request, exc: Exception):
    logger.warning("422 %s — %s", request.url, exc)
    return JSONResponse(
        status_code=422,
        content=_error_body(422, "ValidationError", str(exc), str(request.url.path)),
    )


def _demo_reset():
    """Apaga todos os dados gerados por usuários (tarefas, runs, alertas, artefatos, histórico de chat).
    Os dados operacionais (produção, defeitos, métricas) são preservados.
    Chamado automaticamente à meia-noite para manter o banco enxuto em ambiente de demo.
    """
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM scheduled_tasks")
            conn.execute("DELETE FROM task_runs")
            conn.execute("DELETE FROM task_code_versions")
            conn.execute("DELETE FROM dashboard_widgets")
            conn.execute("UPDATE task_id_sequence SET next_id = 1 WHERE id = 1")
            # Limpa tabelas do checkpointer LangGraph (histórico de conversa)
            for tbl in ("checkpoints", "writes"):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()

        # Alertas e artefatos ficam em uma conexão separada (chart_store)
        cs.delete_all_alerts()
        cs.delete_all_charts()

        # Limpa namespaces Python em memória
        try:
            from agent_multi import _namespaces
            _namespaces.clear()
        except Exception:
            pass

        logger.info("Demo reset executado à meia-noite — dados de usuário removidos.")
    except Exception:
        logger.exception("Falha no demo reset")


async def _daily_date_shifter():
    """Background task: waits until next midnight, then shifts DB dates forward by 1 day. Repeats forever."""
    while True:
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_midnight - now).total_seconds())
        if os.getenv("DEMO_RESET", "false").lower() == "true":
            _demo_reset()
        delta = shift_dates_to_today()
        if delta:
            logger.info("Date shift automático aplicado: +%d dia(s)", delta)


@app.on_event("startup")
async def startup():
    init_db()
    migrate_db()
    _init_vertex()
    delta = shift_dates_to_today()
    if delta:
        logger.info("Date shift inicial: +%d dia(s)", delta)
    asyncio.create_task(_daily_date_shifter())
    asyncio.create_task(scheduler_loop())
    asyncio.create_task(ns_cleanup_loop())


def default_range() -> tuple[str, str]:
    """Retorna (start, end) padrão: últimos 7 dias."""
    end = date.today()
    return (end - timedelta(days=6)).isoformat(), end.isoformat()


def build_filters(
    from_date: Optional[str],
    to_date: Optional[str],
    shift: Optional[str] = None,
    line: Optional[int] = None,
    model: Optional[str] = None,
    table: str = "t",
) -> tuple[str, list]:
    start = from_date or default_range()[0]
    end   = to_date   or default_range()[1]
    clause = f"{table}.date BETWEEN ? AND ?"
    params: list = [start, end]
    if shift:
        clause += f" AND {table}.shift = ?"
        params.append(shift)
    if line:
        clause += f" AND {table}.line = ?"
        params.append(line)
    if model:
        clause += f" AND {table}.model = ?"
        params.append(model)
    return clause, params


# ── chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChartSnapshotRequest(BaseModel):
    session_id: str
    snapshot: dict


@app.post("/chart-snapshot")
async def chart_snapshot(req: ChartSnapshotRequest):
    """Recebe o snapshot atual dos gráficos do dashboard e armazena por session_id."""
    set_chart_snapshot(req.session_id, req.snapshot)
    return {"ok": True}


@app.post("/chat")
async def chat(req: ChatRequest):
    """Envia uma mensagem ao agente LangGraph (Gemini via Vertex AI) e retorna a resposta."""
    if not is_multi_agent_ready():
        return JSONResponse(
            status_code=503,
            content=_error_body(503, "ServiceUnavailable", "Agente IA não configurado. Verifique PROJECT_ID, LOCATION e credentials.json.", "/chat"),
        )
    reply = await asyncio.to_thread(lambda: invoke_multi_agent(req.message, req.session_id))
    return {"reply": _embed_charts(reply)}


@app.get("/chart/{chart_id}")
def serve_chart(chart_id: str):
    """Serve um gráfico gerado pelo agente como PNG."""
    b64 = cs.get_chart_b64(chart_id)
    if not b64:
        return JSONResponse(status_code=404, content={"error": True, "message": "Gráfico não encontrado."})
    import base64
    png_bytes = base64.b64decode(b64)
    return Response(content=png_bytes, media_type="image/png")


@app.get("/pdf/{pdf_id}")
def download_pdf(pdf_id: str):
    """Serve um PDF gerado pelo agente para download."""
    row = cs.get_pdf(pdf_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": True, "message": "PDF não encontrado."})
    pdf_bytes, filename = row
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/excel/{excel_id}")
def download_excel(excel_id: str):
    """Serve uma planilha Excel gerada pelo agente para download."""
    row = cs.get_excel(excel_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": True, "message": "Excel não encontrado."})
    excel_bytes, filename = row
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/chat/stream")
async def chat_stream(request: Request, message: str, session_id: str = "default"):
    """Endpoint SSE — transmite thinking, tool calls e resposta final em tempo real."""
    if not is_multi_agent_ready():
        async def _err():
            yield {"data": json.dumps({"type": "error", "text": "Agente IA não configurado."})}
        return EventSourceResponse(_err())

    async def generate():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _run():
            try:
                for event in stream_multi_agent(message, session_id):
                    if event.get("type") == "reply":
                        event["text"] = _embed_charts(event["text"])
                    asyncio.run_coroutine_threadsafe(queue.put(event), loop)
            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    queue.put({"type": "error", "text": str(e)}), loop
                )
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        threading.Thread(target=_run, daemon=True).start()

        while True:
            if await request.is_disconnected():
                break
            event = await queue.get()
            if event is None:
                break
            yield {"data": json.dumps(event)}

    return EventSourceResponse(generate())


@app.get("/chat/history")
async def chat_history(session_id: str = "default"):
    """Retorna o histórico de mensagens de uma sessão (HumanMessage e AIMessage apenas)."""
    if not is_multi_agent_ready():
        return []
    try:
        from agent_multi import _checkpointer
        if _checkpointer is None:
            return []
        state = _checkpointer.get({"configurable": {"thread_id": session_id}})
        if not state:
            return []
        from langchain_core.messages import HumanMessage, AIMessage
        result = []
        for msg in state.get("channel_values", {}).get("messages", []):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if isinstance(content, list):
                    content = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
                result.append({"role": "user", "content": content or ""})
            elif isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, list):
                    content = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
                result.append({"role": "assistant", "content": _embed_charts(content)})
        return result
    except Exception:
        return []


@app.get("/chat/sessions")
async def list_chat_sessions(user_id: str = Query(default=None)):
    """Lista todas as sessões de chat de um usuário com título e contagem de mensagens."""
    if not is_multi_agent_ready() or not user_id:
        return []
    try:
        from agent_multi import _checkpointer
        from langchain_core.messages import HumanMessage, AIMessage
        if _checkpointer is None:
            return []
        conn = _checkpointer.conn
        rows = conn.execute(
            "SELECT thread_id, MAX(checkpoint_id) as latest FROM checkpoints "
            "WHERE thread_id = ? OR thread_id LIKE ? "
            "GROUP BY thread_id ORDER BY latest DESC",
            (user_id, user_id + "_%"),
        ).fetchall()
        sessions = []
        for row in rows:
            tid = row[0]
            state = _checkpointer.get({"configurable": {"thread_id": tid}})
            if not state:
                continue
            msgs = state.get("channel_values", {}).get("messages", [])
            human_msgs = [
                m for m in msgs
                if isinstance(m, HumanMessage)
                and not str(getattr(m, "content", "")).startswith("[VALIDAÇÃO")
            ]
            if not human_msgs:
                continue
            _tc = human_msgs[0].content
            if isinstance(_tc, list):
                _tc = " ".join(p.get("text", "") for p in _tc if isinstance(p, dict) and p.get("type") == "text")
            title = str(_tc)[:70].strip() or "(sem título)"
            visible_count = sum(
                1 for m in msgs
                if isinstance(m, (HumanMessage, AIMessage))
                and not getattr(m, "tool_calls", None)
                and not str(getattr(m, "content", "")).startswith("[VALIDAÇÃO")
            )
            sessions.append({
                "session_id": tid,
                "title": title,
                "message_count": visible_count,
            })
        return sessions
    except Exception:
        logger.exception("Erro em /chat/sessions")
        return []


@app.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """Deleta uma sessão de chat e todos os artefatos associados."""
    if not is_multi_agent_ready():
        return JSONResponse(status_code=503, content={"error": "Agente IA não configurado"})
    try:
        with get_db() as conn:
            for tbl in ("checkpoints", "writes"):
                try:
                    conn.execute(f"DELETE FROM {tbl} WHERE thread_id = ?", (session_id,))
                except Exception:
                    pass
            conn.commit()
        import chart_store as cs
        cs.delete_charts_for_session(session_id)
        if cs._conn is not None:
            with cs._lock:
                cs._conn.execute("DELETE FROM pdfs WHERE session_id = ?", (session_id,))
                cs._conn.execute("DELETE FROM excels WHERE session_id = ?", (session_id,))
                cs._conn.commit()
        return {"ok": True}
    except Exception:
        logger.exception("Erro em DELETE /chat/sessions/%s", session_id)
        return JSONResponse(status_code=500, content={"error": "Falha ao deletar sessão"})


@app.post("/chat/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """Recebe áudio (webm/opus), transcreve via Gemini (Vertex AI) e retorna texto."""
    if not is_multi_agent_ready():
        return JSONResponse(status_code=503, content={"error": "Agente IA não configurado"})

    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        return JSONResponse(status_code=500, content={"error": "google-genai SDK não disponível"})

    project    = os.getenv("PROJECT_ID", "")
    location   = os.getenv("LOCATION", "us-central1")
    model_name = os.getenv("MODEL_NAME", "gemini-2.0-flash-001")

    audio_bytes = await audio.read()
    mime_type   = audio.content_type or "audio/webm"

    try:
        credentials = _load_credentials()
        client = genai.Client(vertexai=True, project=project, location=location, credentials=credentials)
        contents = genai_types.Content(role="user", parts=[
            genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            genai_types.Part.from_text(text="Transcreva literalmente o áudio. Regras: (1) copie palavra por palavra o que foi dito, sem corrigir, resumir, interpretar ou adicionar nada; (2) retorne apenas o texto transcrito, sem introduções, aspas ou comentários; (3) se não houver fala, retorne uma string vazia."),
        ])
        response = await asyncio.to_thread(
            lambda: client.models.generate_content(model=model_name, contents=contents)
        )
        transcript = (getattr(response, "text", None) or "").strip()
    except Exception as e:
        logger.error("Transcrição via Gemini falhou: %s", e)
        return JSONResponse(status_code=502, content={"error": f"Falha na transcrição: {e}"})

    if not transcript:
        return JSONResponse(status_code=422, content={"error": "Não foi possível transcrever o áudio"})

    return {"transcript": transcript}


# ── raiz ──────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    html = Path(__file__).parent / "mfg-dashboard.html"
    return FileResponse(html, media_type="text/html")


# ── demo controls ─────────────────────────────────────────────────────────────
# Estado computado do banco — resistente a restart e page refresh.
# Na primeira ação do dia o baseline é persistido em demo_baseline.
# Estado derivado comparando soma atual vs soma do baseline:
#   ratio >= 1.4  → "boosted"  (boost desabilitado)
#   ratio <= 0.6  → "reduced"  (reduce desabilitado)
#   caso contrário → "normal"  (ambos habilitados)


def _demo_ensure_baseline(conn, today: str) -> bool:
    """Salva o baseline de hoje se ainda não existe. Retorna False se não há dados."""
    exists = conn.execute(
        "SELECT COUNT(*) FROM demo_baseline WHERE date = ?", (today,)
    ).fetchone()[0]
    if exists:
        return True
    rows = conn.execute(
        "SELECT id, produced FROM production WHERE date = ?", (today,)
    ).fetchall()
    if not rows:
        return False
    conn.executemany(
        "INSERT OR IGNORE INTO demo_baseline (date, prod_id, produced) VALUES (?, ?, ?)",
        [(today, r["id"], r["produced"]) for r in rows],
    )
    conn.commit()
    return True


def _demo_compute_state(conn, today: str) -> str:
    baseline = conn.execute(
        "SELECT SUM(produced) FROM demo_baseline WHERE date = ?", (today,)
    ).fetchone()[0]
    if not baseline:
        return "normal"
    current = conn.execute(
        "SELECT SUM(produced) FROM production WHERE date = ?", (today,)
    ).fetchone()[0] or 0
    ratio = current / baseline
    if ratio >= 1.4:
        return "boosted"
    if ratio <= 0.6:
        return "reduced"
    return "normal"


def _demo_apply_factor(conn, today: str, factor: float) -> None:
    rows = conn.execute(
        "SELECT prod_id, produced FROM demo_baseline WHERE date = ?", (today,)
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE production SET produced = ? WHERE id = ?",
            (round(r["produced"] * factor), r["prod_id"]),
        )


@app.get("/demo/state")
def demo_state():
    """Retorna o estado atual dos controles de demo, computado do banco."""
    today = date.today().isoformat()
    with get_db() as conn:
        state = _demo_compute_state(conn, today)
    return {"state": state}


@app.post("/demo/boost")
def demo_boost():
    """Normal→Alto (+50%). Baixo→Normal (restaura). Bloqueado se já Alto."""
    today = date.today().isoformat()
    with get_db() as conn:
        _demo_ensure_baseline(conn, today)
        state = _demo_compute_state(conn, today)
        if state == "boosted":
            return JSONResponse(status_code=409, content={"error": True, "message": "Já está no estado alto."})
        # reduced → restaura ao original; normal → sobe para +50%
        factor = 1.0 if state == "reduced" else 1.5
        _demo_apply_factor(conn, today, factor)
        conn.commit()
        state = _demo_compute_state(conn, today)
    return {"ok": True, "state": state}


@app.post("/demo/reduce")
def demo_reduce():
    """Normal→Baixo (−50%). Alto→Normal (restaura). Bloqueado se já Baixo."""
    today = date.today().isoformat()
    with get_db() as conn:
        _demo_ensure_baseline(conn, today)
        state = _demo_compute_state(conn, today)
        if state == "reduced":
            return JSONResponse(status_code=409, content={"error": True, "message": "Já está no estado baixo."})
        # boosted → restaura ao original; normal → desce para −50%
        factor = 1.0 if state == "boosted" else 0.5
        _demo_apply_factor(conn, today, factor)
        conn.commit()
        state = _demo_compute_state(conn, today)
    return {"ok": True, "state": state}


# ── agenda ────────────────────────────────────────────────────────────────────

@app.get("/tasks")
def get_tasks(user_id: str = Query(default=None)):
    """Retorna as tarefas agendadas com as últimas 5 execuções de cada uma."""
    with get_db() as conn:
        if user_id:
            tasks = conn.execute(
                "SELECT id, name, description, frequency, time, weekday, day, "
                "email, status, next_run, last_run, created_at, retry_count, max_retries "
                "FROM scheduled_tasks WHERE user_id=? ORDER BY id DESC", (user_id,)
            ).fetchall()
        else:
            tasks = conn.execute(
                "SELECT id, name, description, frequency, time, weekday, day, "
                "email, status, next_run, last_run, created_at, retry_count, max_retries "
                "FROM scheduled_tasks ORDER BY id DESC"
            ).fetchall()
        task_ids = tuple(dict(t)["id"] for t in tasks)
        runs = (
            conn.execute(
                f"SELECT id, task_id, started_at, ended_at, status, error "
                f"FROM task_runs WHERE task_id IN ({','.join('?'*len(task_ids))}) ORDER BY started_at DESC",
                task_ids,
            ).fetchall()
            if task_ids else []
        )

    runs_by_task: dict = {}
    for r in runs:
        d = dict(r)
        runs_by_task.setdefault(d["task_id"], [])
        if len(runs_by_task[d["task_id"]]) < 5:
            runs_by_task[d["task_id"]].append(d)

    result = []
    for t in tasks:
        row = dict(t)
        row["runs"] = runs_by_task.get(row["id"], [])
        result.append(row)
    return result


@app.get("/tasks/{task_id}/runs")
def get_task_runs(task_id: str, user_id: str = Query(default=None)):
    """Retorna o histórico completo de execuções de uma tarefa."""
    with get_db() as conn:
        if user_id:
            exists = conn.execute("SELECT id FROM scheduled_tasks WHERE id=? AND user_id=?", (task_id, user_id)).fetchone()
            if not exists:
                return JSONResponse(status_code=404, content={"error": True, "message": f"Task {task_id} não encontrada."})
        rows = conn.execute(
            "SELECT * FROM task_runs WHERE task_id=? ORDER BY started_at DESC",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/tasks/{task_id}/code-audit")
def get_task_code_audit(task_id: str):
    """Retorna histórico de erros de geração/correção de task_code para auditoria."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, task_id, attempt, phase, error, code, created_at "
            "FROM task_code_audit WHERE task_id=? ORDER BY created_at DESC",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/tasks/code-audit/summary")
def get_code_audit_summary():
    """Resumo de erros de geração de código: padrões, módulos bloqueados, frequência."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, task_id, attempt, phase, error, code, created_at "
            "FROM task_code_audit ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/tasks/code-audit/{audit_id}")
def delete_code_audit_entry(audit_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM task_code_audit WHERE id = ?", (audit_id,))
        conn.commit()
    if cur.rowcount == 0:
        return JSONResponse(status_code=404, content={"error": "Entrada não encontrada."})
    return {"ok": True}


@app.delete("/tasks/code-audit")
def delete_all_code_audit():
    with get_db() as conn:
        conn.execute("DELETE FROM task_code_audit")
        conn.commit()
    return {"ok": True}


@app.post("/tasks/{task_id}/run-now")
async def run_task_now(task_id: str, user_id: str = Query(default=None)):
    """Dispara execução imediata da task em background. Só funciona se status=active."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id=?" + (" AND user_id=?" if user_id else ""),
            (task_id, user_id) if user_id else (task_id,),
        ).fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": True, "message": f"Task {task_id} não encontrada."})
    task = dict(row)
    if task["status"] != "active":
        return JSONResponse(status_code=409, content={"error": True, "message": f"Task deve estar ativa para execução manual (status atual: {task['status']})."})
    asyncio.create_task(asyncio.to_thread(_execute_task, task))
    return {"ok": True, "message": "Execução iniciada."}


@app.post("/tasks/{task_id}/toggle-pause")
def toggle_pause_task(task_id: str, user_id: str = Query(default=None)):
    """Alterna entre pausado e ativo. Não afeta tasks em execução ou concluídas."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, status FROM scheduled_tasks WHERE id=?" + (" AND user_id=?" if user_id else ""),
            (task_id, user_id) if user_id else (task_id,),
        ).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": True, "message": f"Task {task_id} não encontrada."})
        current = row["status"]
        if current not in ("active", "paused"):
            return JSONResponse(status_code=409, content={"error": True, "message": f"Não é possível pausar/retomar task com status '{current}'."})
        new_status = "paused" if current == "active" else "active"
        conn.execute("UPDATE scheduled_tasks SET status=? WHERE id=?", (new_status, task_id))
        conn.commit()
    return {"ok": True, "task_id": task_id, "status": new_status}


@app.delete("/tasks/{task_id}")
def delete_task_endpoint(task_id: str, user_id: str = Query(default=None)):
    """Remove uma tarefa do banco pelo ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM scheduled_tasks WHERE id=?" + (" AND user_id=?" if user_id else ""),
            (task_id, user_id) if user_id else (task_id,),
        ).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": True, "message": f"Task {task_id} não encontrada."})
        conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.commit()
    return {"ok": True, "deleted": task_id}


@app.get("/tasks/{task_id}/code")
def get_task_code(task_id: str, user_id: str = Query(default=None)):
    """Retorna o código atual da tarefa e o histórico de versões anteriores."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name, task_code, instructions FROM scheduled_tasks WHERE id=?"
            + (" AND user_id=?" if user_id else ""),
            (task_id, user_id) if user_id else (task_id,),
        ).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": True, "message": f"Task {task_id} não encontrada."})
        versions = conn.execute(
            "SELECT version, code, created_at FROM task_code_versions WHERE task_id=? ORDER BY version DESC",
            (task_id,),
        ).fetchall()
    return {
        "task_id": task_id,
        "name": row["name"],
        "task_code": row["task_code"],
        "instructions": row["instructions"],
        "versions": [dict(v) for v in versions],
    }


@app.get("/artifacts")
def get_artifacts():
    """Lista todos os artefatos (PDFs, gráficos, Excel) com origem e data."""
    import re as _re
    artifacts = cs.list_artifacts()
    for a in artifacts:
        sid = a.get("session_id", "")
        m = _re.match(r'^daemon_(\d+)_', sid)
        if m:
            a["origin"] = "task"
            a["task_id"] = m.group(1)
        else:
            a["origin"] = "chat"
            a["task_id"] = None
    return artifacts


# ── painéis customizados do dashboard ────────────────────────────────────────

@app.get("/dashboard-widgets")
def get_dashboard_widgets(user_id: str = Query(default=None)):
    """Lista os painéis customizados do dashboard para um usuário."""
    with get_db() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT id, title, description, created_at FROM dashboard_widgets "
                "WHERE user_id=? OR user_id IS NULL ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, description, created_at FROM dashboard_widgets ORDER BY created_at ASC"
            ).fetchall()
    return [dict(r) for r in rows]


@app.get("/dashboard-widgets/{widget_id}/data")
def get_dashboard_widget_data(widget_id: str):
    """Re-executa o widget_code e retorna a configuração Chart.js atualizada."""
    from scheduler.widget_runner import run_widget_code, default_test_range, WidgetCodeError
    from datetime import datetime as _dt

    with get_db() as conn:
        row = conn.execute(
            "SELECT code FROM dashboard_widgets WHERE id = ?", (widget_id,)
        ).fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": True, "message": "Painel não encontrado."})

    from_date, to_date = default_test_range()
    session_id = f"widget_{widget_id[:8]}_{_dt.now().strftime('%Y%m%d%H%M%S')}"
    try:
        config = run_widget_code(row["code"], from_date, to_date, session_id)
    except WidgetCodeError as e:
        return JSONResponse(status_code=422, content={"error": True, "message": str(e)})
    except Exception as e:
        logger.exception("Erro ao executar widget %s", widget_id)
        return JSONResponse(status_code=500, content={"error": True, "message": str(e)})

    return config


@app.delete("/dashboard-widgets/{widget_id}")
def delete_dashboard_widget_endpoint(widget_id: str, user_id: str = Query(default=None)):
    """Remove um painel customizado do dashboard."""
    with get_db() as conn:
        query = "SELECT id FROM dashboard_widgets WHERE id = ?"
        params = [widget_id]
        if user_id:
            query += " AND (user_id = ? OR user_id IS NULL)"
            params.append(user_id)
        row = conn.execute(query, params).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": True, "message": "Painel não encontrado."})
        conn.execute("DELETE FROM dashboard_widgets WHERE id = ?", (widget_id,))
        conn.commit()
    return {"ok": True, "deleted": widget_id}


@app.delete("/artifacts/{artifact_type}/{artifact_id}")
def delete_artifact(artifact_type: str, artifact_id: str):
    """Remove um artefato do banco pelo tipo e ID."""
    ok = cs.delete_artifact(artifact_type, artifact_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": True, "message": "Artefato não encontrado."})
    return {"ok": True}


@app.get("/reports/{task_id}")
def get_reports_for_task(task_id: str):
    """Lista os relatórios gerados para uma task, mais recente primeiro."""
    reports_dir = Path(__file__).parent / "reports"
    if not reports_dir.exists():
        return []
    results = []
    for folder in sorted(reports_dir.iterdir(), reverse=True):
        if not folder.is_dir() or not folder.name.startswith(f"{task_id}_"):
            continue
        meta_file = folder / "metadata.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        results.append({
            "folder": folder.name,
            "run_at": meta.get("run_at"),
            "status": meta.get("status"),
            "pdf_urls": meta.get("pdf_urls", []),
        })
    return results


# ── produção ──────────────────────────────────────────────────────────────────

@app.get("/production")
def get_production(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
    shift:     Optional[Literal["A", "B", "C"]] = None,
    line:      Optional[int] = None,
    model:     Optional[str] = None,
):
    """
    Produção agregada por dia no período.
    Filtre por turno, linha e/ou modelo para recortes específicos.

    Exemplos:
      /production?from=2026-05-01&to=2026-05-15
      /production?from=2026-05-01&to=2026-05-15&line=1
      /production?from=2026-05-01&to=2026-05-15&shift=A&model=PhoneX+Pro
    """
    clause, params = build_filters(from_date, to_date, shift, line, model, table="p")
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT date, SUM(produced) as produced, SUM(target) as target "
            f"FROM production p WHERE {clause} GROUP BY date ORDER BY date",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/production/historical")
def get_historical_compat(
    range_: str = Query(default="7d", alias="range"),
    shift:     Optional[Literal["A", "B", "C"]] = None,
    line:      Optional[int] = None,
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
):
    """Endpoint de compatibilidade com o dashboard. Monta o formato antigo a partir das novas tabelas."""
    shift_filter   = "AND p.shift = ?" if shift else ""
    shift_filter_d = "AND d.shift = ?" if shift else ""
    shift_params   = [shift] if shift else []
    line_filter    = "AND p.line = ?" if line else ""
    line_params    = [line] if line else []
    line_filter_d  = "AND d.line = ?" if line else ""

    if range_ == "shift":
        with get_db() as conn:
            kpis = {r["shift"]: dict(r) for r in conn.execute("SELECT * FROM kpis").fetchall()}
            def_rows = conn.execute(
                "SELECT shift, category, SUM(count) as count FROM defects GROUP BY shift, category"
            ).fetchall()
        def_by_shift: dict = {"A": {}, "B": {}, "C": {}}
        for r in def_rows:
            def_by_shift[r["shift"]][r["category"]] = r["count"]
        result = []
        shifts_to_show = [shift] if shift else ["A", "B", "C"]
        labels = {"A": "Turno A", "B": "Turno B", "C": "Turno C"}
        for s in shifts_to_show:
            k = kpis[s]
            d = def_by_shift[s]
            result.append({
                "label": labels[s], "produced": k["total_produced"], "target": k["daily_target"],
                "fpy": k["first_pass_yield"], "oee": k["oee"],
                "availability": 0, "performance": 0,
                "line1": 0, "line2": 0, "line3": 0, "line4": 0,
                "shift_a_efficiency": k["efficiency"] if s == "A" else 0,
                "shift_b_efficiency": k["efficiency"] if s == "B" else 0,
                "shift_c_efficiency": k["efficiency"] if s == "C" else 0,
                "defect_screen":  d.get("Tela (display)", 0),
                "defect_camera":  d.get("Câmera", 0),
                "defect_battery": d.get("Bateria", 0),
                "defect_other":   sum(v for k2, v in d.items() if k2 not in ("Tela (display)", "Câmera", "Bateria")),
            })
        return result

    if from_date and to_date:
        start, end = from_date, to_date
    else:
        days = {"7d": 7, "14d": 14, "30d": 30}.get(range_, 7)
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=days - 1)).isoformat()

    with get_db() as conn:
        prod = {r["date"]: dict(r) for r in conn.execute(
            f"SELECT date, SUM(produced) as produced, SUM(target) as target FROM production p WHERE p.date BETWEEN ? AND ? {shift_filter} {line_filter} GROUP BY date",
            [start, end] + shift_params + line_params,
        ).fetchall()}
        lines = conn.execute(
            f"SELECT date, line, SUM(produced) as produced FROM production p WHERE p.date BETWEEN ? AND ? {shift_filter} {line_filter} GROUP BY date, line",
            [start, end] + shift_params + line_params,
        ).fetchall()
        metrics_rows = {r["date"]: dict(r) for r in conn.execute(
            "SELECT * FROM metrics WHERE date BETWEEN ? AND ? ORDER BY date",
            (start, end),
        ).fetchall()}
        def_total = {r["date"]: r["count"] for r in conn.execute(
            f"SELECT date, SUM(count) as count FROM defects d WHERE d.date BETWEEN ? AND ? {shift_filter_d} {line_filter_d} GROUP BY date",
            [start, end] + shift_params + line_params,
        ).fetchall()}
        def_cat = conn.execute(
            f"SELECT date, category, SUM(count) as count FROM defects d WHERE d.date BETWEEN ? AND ? {shift_filter_d} {line_filter_d} GROUP BY date, category",
            [start, end] + shift_params + line_params,
        ).fetchall()

        # quando linha filtrada, eficiência por turno vem da production (produzido/meta×100)
        # sem filtro de linha, vem da tabela metrics (factory-wide)
        eff_by_date: dict = {}
        if line:
            for r in conn.execute(
                f"SELECT date, shift, ROUND(CAST(SUM(produced) AS REAL) / SUM(target) * 100, 1) as eff "
                f"FROM production p WHERE p.date BETWEEN ? AND ? {line_filter} GROUP BY date, shift",
                [start, end] + line_params,
            ).fetchall():
                eff_by_date.setdefault(r["date"], {})[r["shift"]] = r["eff"]

    # organiza produção por linha
    line_by_date: dict = {}
    for r in lines:
        line_by_date.setdefault(r["date"], {})[r["line"]] = r["produced"]

    # organiza defeitos por categoria
    def_by_date: dict = {}
    for r in def_cat:
        def_by_date.setdefault(r["date"], {})[r["category"]] = r["count"]

    # chaves de FPY e OEE dependem do turno selecionado
    fpy_key = f"fpy_{shift.lower()}" if shift else None
    oee_key = f"oee_{shift.lower()}" if shift else None
    _PT_DAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

    result = []
    for d in sorted(prod.keys()):
        m = metrics_rows.get(d, {})
        ld = line_by_date.get(d, {})
        dd = def_by_date.get(d, {})
        # FPY e OEE: usa o valor do turno selecionado, ou média dos três
        if line:
            p = prod[d]["produced"]
            d_count = def_total.get(d, 0)
            fpy = round((p - d_count) / p * 100, 1) if p > 0 else 0
        else:
            fpy = m.get(fpy_key, 0) if fpy_key else round((m.get("fpy_a",0) + m.get("fpy_b",0) + m.get("fpy_c",0)) / 3, 1)
        if line:
            avail = m.get("availability", 0) / 100
            perf  = m.get("performance",  0) / 100
            oee   = round(avail * perf * (fpy / 100) * 100, 1)
        else:
            oee = m.get(oee_key, 0) if oee_key else round((m.get("oee_a",0) + m.get("oee_b",0) + m.get("oee_c",0)) / 3, 1)
        result.append({
            "date":  d,
            "label": _PT_DAYS[date.fromisoformat(d).weekday()],
            "produced": prod[d]["produced"],
            "defects":  def_total.get(d, 0),
            "target":   prod[d]["target"],
            "fpy":          fpy,
            "oee":          oee,
            "availability": m.get("availability", 0),
            "performance":  m.get("performance", 0),
            "line1": ld.get(1, 0), "line2": ld.get(2, 0),
            "line3": ld.get(3, 0), "line4": ld.get(4, 0),
            "shift_a_efficiency": (eff_by_date.get(d, {}).get("A", 0) if line else m.get("shift_a_efficiency", 0)) if not shift or shift == "A" else 0,
            "shift_b_efficiency": (eff_by_date.get(d, {}).get("B", 0) if line else m.get("shift_b_efficiency", 0)) if not shift or shift == "B" else 0,
            "shift_c_efficiency": (eff_by_date.get(d, {}).get("C", 0) if line else m.get("shift_c_efficiency", 0)) if not shift or shift == "C" else 0,
            "defect_screen":  dd.get("Tela (display)", 0),
            "defect_camera":  dd.get("Câmera", 0),
            "defect_battery": dd.get("Bateria", 0),
            "defect_other":   sum(v for k, v in dd.items() if k not in ("Tela (display)", "Câmera", "Bateria")),
        })
    return result


@app.get("/production/hourly")
def get_hourly_production(
    shift:     Literal["A", "B", "C"] = "A",
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
    line:      Optional[int] = None,
):
    """
    Média e desvio padrão de produção por hora do turno no período.
    Sem from/to: últimos 7 dias. Filtre por linha para ver uma linha específica.

    Exemplos:
      /production/hourly?shift=A
      /production/hourly?shift=B&from=2026-05-01&to=2026-05-15&line=1
    """
    start = from_date or default_range()[0]
    end   = to_date   or default_range()[1]
    with get_db() as conn:
        if line:
            # Filtra uma linha: AVG direto por hora
            rows = conn.execute(
                """
                SELECT
                    hour,
                    ROUND(AVG(produced), 1)  AS avg_produced,
                    ROUND(SQRT(MAX(0.0, AVG(produced*produced) - AVG(produced)*AVG(produced))), 1) AS stddev_produced,
                    ROUND(AVG(defects), 1)   AS avg_defects,
                    ROUND(SQRT(MAX(0.0, AVG(defects*defects) - AVG(defects)*AVG(defects))), 1)    AS stddev_defects,
                    ROUND(AVG(target), 0)    AS avg_target
                FROM hourly_production
                WHERE shift = ? AND date BETWEEN ? AND ? AND line = ?
                GROUP BY hour
                ORDER BY MIN(id)
                """,
                (shift, start, end, line),
            ).fetchall()
        else:
            # Sem modelo: soma todas as linhas por (date, hour), depois AVG entre dias
            rows = conn.execute(
                """
                SELECT
                    hour,
                    ROUND(AVG(day_prod), 1)  AS avg_produced,
                    ROUND(SQRT(MAX(0.0, AVG(day_prod*day_prod) - AVG(day_prod)*AVG(day_prod))), 1) AS stddev_produced,
                    ROUND(AVG(day_def), 1)   AS avg_defects,
                    ROUND(SQRT(MAX(0.0, AVG(day_def*day_def) - AVG(day_def)*AVG(day_def))), 1)    AS stddev_defects,
                    ROUND(AVG(day_tgt), 0)   AS avg_target
                FROM (
                    SELECT date, hour, MIN(id) AS min_id,
                        SUM(produced) AS day_prod,
                        SUM(defects)  AS day_def,
                        SUM(target)   AS day_tgt
                    FROM hourly_production
                    WHERE shift = ? AND date BETWEEN ? AND ?
                    GROUP BY date, hour
                )
                GROUP BY hour
                ORDER BY MIN(min_id)
                """,
                (shift, start, end),
            ).fetchall()
    return [dict(r) for r in rows]


# ── defeitos ──────────────────────────────────────────────────────────────────

@app.get("/defects")
def get_defects(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
    shift:     Optional[Literal["A", "B", "C"]] = None,
    line:      Optional[int] = None,
    category:  Optional[str] = None,
):
    """
    Sem `category`: retorna defeitos agregados por categoria no período.
    Com `category`: retorna série temporal (um ponto por dia).

    Exemplos:
      /defects?from=2026-05-01&to=2026-05-15&line=1
      /defects?from=2026-05-01&to=2026-05-15&category=Tela (display)
      /defects?from=2026-05-01&to=2026-05-15&shift=A&line=1
    """
    clause, params = build_filters(from_date, to_date, shift, line, table="d")

    if category:
        with get_db() as conn:
            rows = conn.execute(
                f"SELECT date, SUM(count) as count FROM defects d "
                f"WHERE {clause} AND d.category = ? GROUP BY date ORDER BY date",
                params + [category],
            ).fetchall()
        return [dict(r) for r in rows]

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT category, SUM(count) as count FROM defects d "
            f"WHERE {clause} GROUP BY category ORDER BY count DESC",
            params,
        ).fetchall()
    total = sum(r["count"] for r in rows)
    return [
        {"category": r["category"], "count": r["count"],
         "percentage": round(r["count"] / total * 100, 1) if total else 0}
        for r in rows
    ]


# ── métricas (OEE, FPY, eficiência) ──────────────────────────────────────────

@app.get("/metrics")
def get_metrics(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
):
    """
    OEE, FPY, disponibilidade e eficiência por turno, por dia.

    Exemplo:
      /metrics?from=2026-05-01&to=2026-05-15
    """
    start = from_date or default_range()[0]
    end   = to_date   or default_range()[1]
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM metrics WHERE date BETWEEN ? AND ? ORDER BY date",
            (start, end),
        ).fetchall()
    return [{k: v for k, v in dict(r).items() if k != "id"} for r in rows]


# ── status das linhas ─────────────────────────────────────────────────────────

@app.get("/lines")
def get_lines():
    """Retorna as linhas de produção com o modelo que cada uma está produzindo atualmente."""
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, model FROM lines_status ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.get("/lines/status")
def get_lines_status():
    """Status em tempo real das linhas (snapshot atual)."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM lines_status ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ── alertas ───────────────────────────────────────────────────────────────────

@app.get("/alerts")
def get_alerts(all: bool = False, user_id: str = Query(default=None)):
    """Retorna alertas de threshold. Por padrão apenas não lidos; ?all=true retorna os últimos 100."""
    return cs.get_alerts(unread_only=not all, user_id=user_id)


@app.post("/alerts/{alert_id}/read")
def mark_alert_read(alert_id: str, user_id: str = Query(default=None)):
    """Marca um alerta como lido."""
    ok = cs.mark_alert_read(alert_id, user_id=user_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": True, "message": "Alerta não encontrado."})
    return {"ok": True}


@app.post("/alerts/read-all")
def mark_all_alerts_read(user_id: str = Query(default=None)):
    """Marca todos os alertas não lidos como lidos."""
    count = cs.mark_all_alerts_read(user_id=user_id)
    return {"ok": True, "marked": count}


@app.delete("/alerts")
def delete_all_alerts(user_id: str = Query(default=None)):
    """Apaga todos os alertas permanentemente."""
    count = cs.delete_all_alerts(user_id=user_id)
    return {"ok": True, "deleted": count}


@app.delete("/alerts/{alert_id}")
def delete_alert(alert_id: str, user_id: str = Query(default=None)):
    """Apaga permanentemente um alerta."""
    ok = cs.delete_alert(alert_id, user_id=user_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": True, "message": "Alerta não encontrado."})
    return {"ok": True}


# ── kpis (snapshot por turno) ─────────────────────────────────────────────────

@app.get("/kpis")
def get_kpis(
    shift:     Literal["A", "B", "C"] = "A",
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
    line:      Optional[int] = None,
):
    """
    KPIs calculados dinamicamente para o período selecionado.
    Sem from/to: usa apenas o dia de hoje (comportamento original).
    """
    start = from_date or date.today().isoformat()
    end   = to_date   or date.today().isoformat()
    line_clause  = "AND line = ?" if line else ""
    line_params  = [line] if line else []

    with get_db() as conn:
        prod = conn.execute(
            f"SELECT SUM(produced) as produced, SUM(target) as target "
            f"FROM production WHERE shift = ? AND date BETWEEN ? AND ? {line_clause}",
            [shift, start, end] + line_params,
        ).fetchone()

        fpy_col = f"fpy_{shift.lower()}"
        oee_col = f"oee_{shift.lower()}"
        met = conn.execute(
            f"""SELECT
                AVG({fpy_col}) as fpy,
                SQRT(MAX(0.0, AVG({fpy_col}*{fpy_col}) - AVG({fpy_col})*AVG({fpy_col}))) as stddev_fpy,
                AVG({oee_col}) as oee,
                SQRT(MAX(0.0, AVG({oee_col}*{oee_col}) - AVG({oee_col})*AVG({oee_col}))) as stddev_oee,
                AVG(availability) as avail,
                AVG(performance) as perf
            FROM metrics WHERE date BETWEEN ? AND ?""",
            (start, end),
        ).fetchone()

        def_total = conn.execute(
            f"SELECT SUM(count) as count FROM defects WHERE shift = ? AND date BETWEEN ? AND ? {line_clause}",
            [shift, start, end] + line_params,
        ).fetchone()

        # downtime e rework não têm série temporal — usa snapshot como referência por dia
        days = max(1, (date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
        snap = conn.execute("SELECT * FROM kpis WHERE shift = ?", (shift,)).fetchone()

    produced = prod["produced"] or 0
    defects  = def_total["count"] or 0

    return {
        "shift":               shift,
        "total_produced":      produced,
        "daily_target":        (prod["target"] or 0),
        "first_pass_yield":    round(met["fpy"]      or 0, 1),
        "stddev_fpy":          round(met["stddev_fpy"] or 0, 1),
        "oee":                 round(met["oee"]      or 0, 1),
        "stddev_oee":          round(met["stddev_oee"] or 0, 1),
        "defect_rate":         round(defects / produced * 100, 1) if produced > 0 else 0,
        "scrapped":            defects,
        "reworked":            snap["reworked"] * days,
        "downtime_minutes":    snap["downtime_minutes"] * days,
        "cycle_time_seconds":  snap["cycle_time_seconds"],
        "efficiency":          round(met["perf"] or 0, 1),
    }
