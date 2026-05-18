"""
Camada de persistência de gráficos gerados pelo agente.

Storage: tabela `charts` no mesmo mfg.db usado pelo checkpointer LangGraph.
Troca futura (ex: GCS): basta reimplementar save_chart / get_chart_b64
sem tocar no agente nem no frontend.
"""

import base64
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def init_chart_store(db_path: Path) -> None:
    global _conn
    _conn = sqlite3.connect(str(db_path), check_same_thread=False)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS charts (
            chart_id   TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            png_blob   BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS pdfs (
            pdf_id     TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            pdf_blob   BLOB NOT NULL,
            filename   TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS excels (
            excel_id   TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            excel_blob BLOB NOT NULL,
            filename   TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    _conn.commit()


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def save_chart(session_id: str, png_bytes: bytes) -> str:
    if _conn is None:
        raise RuntimeError("chart_store não inicializado.")
    chart_id = str(uuid.uuid4())
    with _lock:
        _conn.execute(
            "INSERT INTO charts (chart_id, session_id, png_blob, created_at) VALUES (?, ?, ?, ?)",
            (chart_id, session_id, png_bytes, _now()),
        )
        _conn.commit()
    return chart_id


def save_pdf(session_id: str, pdf_bytes: bytes, filename: str) -> str:
    if _conn is None:
        raise RuntimeError("chart_store não inicializado.")
    pdf_id = str(uuid.uuid4())
    with _lock:
        _conn.execute(
            "INSERT INTO pdfs (pdf_id, session_id, pdf_blob, filename, created_at) VALUES (?, ?, ?, ?, ?)",
            (pdf_id, session_id, pdf_bytes, filename, _now()),
        )
        _conn.execute("DELETE FROM charts WHERE session_id = ?", (session_id,))
        _conn.commit()
    return pdf_id


def delete_chart(chart_id: str) -> None:
    if _conn is None:
        return
    with _lock:
        _conn.execute("DELETE FROM charts WHERE chart_id = ?", (chart_id,))
        _conn.commit()


def delete_charts_for_session(session_id: str) -> None:
    if _conn is None:
        return
    with _lock:
        _conn.execute("DELETE FROM charts WHERE session_id = ?", (session_id,))
        _conn.commit()


def get_pdf(pdf_id: str) -> tuple[bytes, str] | None:
    if _conn is None:
        return None
    with _lock:
        row = _conn.execute(
            "SELECT pdf_blob, filename FROM pdfs WHERE pdf_id = ?", (pdf_id,)
        ).fetchone()
    if not row:
        return None
    return row[0], row[1]


def save_excel(session_id: str, excel_bytes: bytes, filename: str) -> str:
    if _conn is None:
        raise RuntimeError("chart_store não inicializado.")
    excel_id = str(uuid.uuid4())
    with _lock:
        _conn.execute(
            "INSERT INTO excels (excel_id, session_id, excel_blob, filename, created_at) VALUES (?, ?, ?, ?, ?)",
            (excel_id, session_id, excel_bytes, filename, _now()),
        )
        _conn.commit()
    return excel_id


def get_excel(excel_id: str) -> tuple[bytes, str] | None:
    if _conn is None:
        return None
    with _lock:
        row = _conn.execute(
            "SELECT excel_blob, filename FROM excels WHERE excel_id = ?", (excel_id,)
        ).fetchone()
    if not row:
        return None
    return row[0], row[1]


def list_artifacts() -> list[dict]:
    """Retorna artefatos ordenados por data desc.

    Gráficos de sessões que também produziram um PDF são omitidos — eles já
    estão embutidos no PDF e não precisam aparecer como item separado.
    """
    if _conn is None:
        return []
    with _lock:
        charts = _conn.execute(
            "SELECT chart_id, session_id, created_at FROM charts ORDER BY created_at DESC"
        ).fetchall()
        pdfs = _conn.execute(
            "SELECT pdf_id, session_id, filename, created_at FROM pdfs ORDER BY created_at DESC"
        ).fetchall()
        excels = _conn.execute(
            "SELECT excel_id, session_id, filename, created_at FROM excels ORDER BY created_at DESC"
        ).fetchall()

    result = []
    for row in charts:
        result.append({"type": "chart", "id": row[0], "session_id": row[1], "created_at": row[2]})
    for row in pdfs:
        result.append({"type": "pdf", "id": row[0], "session_id": row[1], "filename": row[2], "created_at": row[3]})
    for row in excels:
        result.append({"type": "excel", "id": row[0], "session_id": row[1], "filename": row[2], "created_at": row[3]})

    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result


def promote_test_artifacts(task_id: str, real_session_id: str) -> None:
    """Move artifacts de sessão test_{task_id}_* para a sessão real do chat.

    Chamado após save_task_code para que o preview do teste apareça no
    painel de artifacts com a sessão correta (não filtrada).
    """
    if _conn is None:
        return
    prefix = f"test_{task_id}_%"
    with _lock:
        for table in ("charts", "pdfs", "excels"):
            _conn.execute(
                f"UPDATE {table} SET session_id = ? WHERE session_id LIKE ?",
                (real_session_id, prefix),
            )
        _conn.commit()


def delete_artifact(artifact_type: str, artifact_id: str) -> bool:
    if _conn is None:
        return False
    table_col = {"chart": ("charts", "chart_id"), "pdf": ("pdfs", "pdf_id"), "excel": ("excels", "excel_id")}
    if artifact_type not in table_col:
        return False
    table, col = table_col[artifact_type]
    with _lock:
        cur = _conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (artifact_id,))
        _conn.commit()
    return cur.rowcount > 0


def get_chart_b64(chart_id: str) -> str | None:
    if _conn is None:
        return None
    with _lock:
        row = _conn.execute(
            "SELECT png_blob FROM charts WHERE chart_id = ?", (chart_id,)
        ).fetchone()
    if not row:
        return None
    return base64.b64encode(row[0]).decode()
