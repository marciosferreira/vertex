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
    _conn.commit()


def save_chart(session_id: str, png_bytes: bytes) -> str:
    if _conn is None:
        raise RuntimeError("chart_store não inicializado.")
    chart_id = str(uuid.uuid4())
    with _lock:
        _conn.execute(
            "INSERT INTO charts (chart_id, session_id, png_blob) VALUES (?, ?, ?)",
            (chart_id, session_id, png_bytes),
        )
        _conn.commit()
    return chart_id


def save_pdf(session_id: str, pdf_bytes: bytes, filename: str) -> str:
    if _conn is None:
        raise RuntimeError("chart_store não inicializado.")
    pdf_id = str(uuid.uuid4())
    with _lock:
        _conn.execute(
            "INSERT INTO pdfs (pdf_id, session_id, pdf_blob, filename) VALUES (?, ?, ?, ?)",
            (pdf_id, session_id, pdf_bytes, filename),
        )
        _conn.commit()
    return pdf_id


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
