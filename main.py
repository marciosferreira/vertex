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
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db import get_db, init_db

try:
    from dotenv import load_dotenv
    _VERTEX_AVAILABLE = True
except ImportError:
    _VERTEX_AVAILABLE = False

from agent_multi import init_multi_agent, invoke_multi_agent, is_multi_agent_ready


def _init_vertex():
    if not _VERTEX_AVAILABLE:
        logger.warning("python-dotenv não instalado — chat IA desabilitado")
        return
    try:
        load_dotenv()
        creds = Path(__file__).parent / "credentials.json"
        if creds.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds)
        project    = os.getenv("PROJECT_ID")
        location   = os.getenv("LOCATION", "us-central1")
        model_name = os.getenv("MODEL_NAME", "gemini-2.5-flash")
        if not project:
            logger.warning("PROJECT_ID não definido — chat IA desabilitado")
            return
        init_multi_agent(project=project, location=location, model_name=model_name)
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


@app.on_event("startup")
def startup():
    init_db()
    _init_vertex()


def default_range() -> tuple[str, str]:
    """Retorna (start, end) padrão: últimos 7 dias."""
    end = date.today()
    return (end - timedelta(days=6)).isoformat(), end.isoformat()


def build_filters(
    from_date: Optional[str],
    to_date: Optional[str],
    shift: Optional[str] = None,
    line: Optional[int] = None,
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
    return clause, params


# ── chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(req: ChatRequest):
    """Envia uma mensagem ao agente LangGraph (Gemini via Vertex AI) e retorna a resposta."""
    if not is_multi_agent_ready():
        return JSONResponse(
            status_code=503,
            content=_error_body(503, "ServiceUnavailable", "Agente IA não configurado. Verifique PROJECT_ID, LOCATION e credentials.json.", "/chat"),
        )
    reply = await asyncio.to_thread(invoke_multi_agent, req.message)
    return {"reply": reply}


# ── raiz ──────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "MFG Control API", "version": "4.0.0"}


# ── produção ──────────────────────────────────────────────────────────────────

@app.get("/production")
def get_production(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
    shift:     Optional[Literal["A", "B", "C"]] = None,
    line:      Optional[int] = None,
):
    """
    Produção agregada por dia no período.
    Filtre por turno e/ou linha para recortes específicos.

    Exemplos:
      /production?from=2026-05-01&to=2026-05-15
      /production?from=2026-05-01&to=2026-05-15&line=1
      /production?from=2026-05-01&to=2026-05-15&shift=A&line=2
    """
    clause, params = build_filters(from_date, to_date, shift, line, table="p")
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
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
):
    """Endpoint de compatibilidade com o dashboard. Monta o formato antigo a partir das novas tabelas."""
    shift_filter     = "AND p.shift = ?" if shift else ""
    shift_filter_d   = "AND d.shift = ?" if shift else ""
    shift_params     = [shift] if shift else []

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
            f"SELECT date, SUM(produced) as produced, SUM(target) as target FROM production p WHERE p.date BETWEEN ? AND ? {shift_filter} GROUP BY date",
            [start, end] + shift_params,
        ).fetchall()}
        lines = conn.execute(
            f"SELECT date, line, SUM(produced) as produced FROM production p WHERE p.date BETWEEN ? AND ? {shift_filter} GROUP BY date, line",
            [start, end] + shift_params,
        ).fetchall()
        metrics_rows = {r["date"]: dict(r) for r in conn.execute(
            "SELECT * FROM metrics WHERE date BETWEEN ? AND ? ORDER BY date",
            (start, end),
        ).fetchall()}
        def_total = {r["date"]: r["count"] for r in conn.execute(
            f"SELECT date, SUM(count) as count FROM defects d WHERE d.date BETWEEN ? AND ? {shift_filter_d} GROUP BY date",
            [start, end] + shift_params,
        ).fetchall()}
        def_cat = conn.execute(
            f"SELECT date, category, SUM(count) as count FROM defects d WHERE d.date BETWEEN ? AND ? {shift_filter_d} GROUP BY date, category",
            [start, end] + shift_params,
        ).fetchall()

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

    result = []
    for d in sorted(prod.keys()):
        m = metrics_rows.get(d, {})
        ld = line_by_date.get(d, {})
        dd = def_by_date.get(d, {})
        # FPY e OEE: usa o valor do turno selecionado, ou média dos três
        fpy = m.get(fpy_key, 0) if fpy_key else round((m.get("fpy_a",0) + m.get("fpy_b",0) + m.get("fpy_c",0)) / 3, 1)
        oee = m.get(oee_key, 0) if oee_key else round((m.get("oee_a",0) + m.get("oee_b",0) + m.get("oee_c",0)) / 3, 1)
        result.append({
            "date":  d,
            "label": m.get("label", ""),
            "produced": prod[d]["produced"],
            "defects":  def_total.get(d, 0),
            "target":   prod[d]["target"],
            "fpy":          fpy,
            "oee":          oee,
            "availability": m.get("availability", 0),
            "performance":  m.get("performance", 0),
            "line1": ld.get(1, 0), "line2": ld.get(2, 0),
            "line3": ld.get(3, 0), "line4": ld.get(4, 0),
            "shift_a_efficiency": m.get("shift_a_efficiency", 0) if not shift or shift == "A" else 0,
            "shift_b_efficiency": m.get("shift_b_efficiency", 0) if not shift or shift == "B" else 0,
            "shift_c_efficiency": m.get("shift_c_efficiency", 0) if not shift or shift == "C" else 0,
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
):
    """
    Média e desvio padrão de produção por hora do turno no período.
    Sem from/to: últimos 7 dias.

    Exemplos:
      /production/hourly?shift=A
      /production/hourly?shift=B&from=2026-05-01&to=2026-05-15
    """
    start = from_date or default_range()[0]
    end   = to_date   or default_range()[1]
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                hour,
                ROUND(AVG(produced), 1)  AS avg_produced,
                ROUND(SQRT(MAX(0.0, AVG(produced * produced) - AVG(produced) * AVG(produced))), 1) AS stddev_produced,
                ROUND(AVG(defects), 1)   AS avg_defects,
                ROUND(SQRT(MAX(0.0, AVG(defects * defects) - AVG(defects) * AVG(defects))), 1)    AS stddev_defects,
                ROUND(AVG(target), 0)    AS avg_target
            FROM hourly_production
            WHERE shift = ? AND date BETWEEN ? AND ?
            GROUP BY hour
            ORDER BY MIN(id)
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
      /defects?from=2026-05-01&to=2026-05-15&shift=A&line=2&category=Câmera
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

@app.get("/lines/status")
def get_lines_status():
    """Status em tempo real das linhas (snapshot atual)."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM lines_status ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ── alertas ───────────────────────────────────────────────────────────────────


# ── kpis (snapshot por turno) ─────────────────────────────────────────────────

@app.get("/kpis")
def get_kpis(
    shift:     Literal["A", "B", "C"] = "A",
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date:   Optional[str] = Query(default=None, alias="to"),
):
    """
    KPIs calculados dinamicamente para o período selecionado.
    Sem from/to: usa apenas o dia de hoje (comportamento original).
    """
    start = from_date or date.today().isoformat()
    end   = to_date   or date.today().isoformat()

    with get_db() as conn:
        prod = conn.execute(
            "SELECT SUM(produced) as produced, SUM(target) as target "
            "FROM production WHERE shift = ? AND date BETWEEN ? AND ?",
            (shift, start, end),
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
            "SELECT SUM(count) as count FROM defects WHERE shift = ? AND date BETWEEN ? AND ?",
            (shift, start, end),
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
