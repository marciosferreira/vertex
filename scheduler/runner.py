"""
Runner determinístico para task_code.

O código da task deve definir uma função `run(from_date, to_date, ctx)` que
recebe as datas do período e um TaskContext, executa a lógica e retorna
o(s) token(s) dos artifacts gerados (str ou list[str]).

Execução via exec() com namespace controlado — apenas bibliotecas explicitamente
aprovadas ficam disponíveis. Sem acesso a os, subprocess, sys, open, etc.
"""

import builtins
import traceback
from datetime import date, timedelta

from .context import TaskContext


# ── Bibliotecas aprovadas para o namespace das tasks ─────────────────────────

def _build_globals(ctx: TaskContext, from_date: str, to_date: str) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import numpy as np
    import pandas as pd
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from datetime import date as _date, datetime as _datetime, timedelta as _timedelta

    # __import__ precisa existir no dict de builtins ou o Python levanta KeyError
    # internamente. Fornecemos uma versão que bloqueia com mensagem clara.
    def _blocked_import(name, *args, **kwargs):
        raise ImportError(
            f"Import de '{name}' não é permitido dentro do run(). "
            "Use as variáveis já disponíveis no namespace: "
            "pd, np, plt, date, datetime, timedelta, openpyxl, ctx, etc."
        )

    safe_builtins = {
        name: getattr(builtins, name)
        for name in (
            "abs", "all", "any", "bool", "dict", "divmod", "enumerate",
            "filter", "float", "format", "frozenset", "getattr", "hasattr",
            "hash", "int", "isinstance", "issubclass", "iter", "len", "list",
            "map", "max", "min", "next", "object", "print", "range", "repr",
            "reversed", "round", "set", "slice", "sorted", "str", "sum",
            "tuple", "type", "zip", "True", "False", "None",
            "ValueError", "TypeError", "KeyError", "IndexError",
            "RuntimeError", "StopIteration", "Exception",
        )
    }
    safe_builtins["__import__"] = _blocked_import

    return {
        "__builtins__": safe_builtins,
        # datas do período
        "from_date": from_date,
        "to_date":   to_date,
        # datetime — não usar import dentro do run(), já está disponível
        "date":      _date,
        "datetime":  _datetime,
        "timedelta": _timedelta,
        # contexto com api() e save_*()
        "ctx": ctx,
        # matplotlib
        "plt":      plt,
        "mticker":  mticker,
        # numpy / pandas
        "np":  np,
        "pd":  pd,
        # openpyxl
        "openpyxl":          openpyxl,
        "Font":              Font,
        "PatternFill":       PatternFill,
        "Alignment":         Alignment,
        "Border":            Border,
        "Side":              Side,
        "get_column_letter": get_column_letter,
    }


# ── Executor ──────────────────────────────────────────────────────────────────

class TaskCodeError(Exception):
    """Erro de validação ou execução do task_code."""


def run_task_code(code: str, from_date: str, to_date: str, session_id: str, user_id: str | None = None) -> list[str]:
    """Compila e executa task_code. Retorna lista de tokens de artifacts.

    Lança TaskCodeError com mensagem amigável em caso de falha.
    """
    ctx = TaskContext(session_id, user_id=user_id)
    g   = _build_globals(ctx, from_date, to_date)

    # 1. Compila — detecta erros de sintaxe antes de executar
    try:
        compiled = compile(code, "<task_code>", "exec")
    except SyntaxError as e:
        raise TaskCodeError(f"Erro de sintaxe no código:\n{e}") from e

    # 2. Executa o bloco — registra a função `run` no namespace
    try:
        exec(compiled, g)
    except Exception as e:
        raise TaskCodeError(
            f"Erro ao carregar o código:\n{traceback.format_exc(limit=8)}"
        ) from e

    # 3. Valida que `run` foi definido
    if "run" not in g or not callable(g["run"]):
        raise TaskCodeError(
            "O código deve definir uma função `run(from_date, to_date, ctx)`."
        )

    # 4. Chama run()
    try:
        result = g["run"](from_date, to_date, ctx)
    except Exception as e:
        raise TaskCodeError(
            f"Erro durante a execução de run():\n{traceback.format_exc(limit=12)}"
        ) from e

    # 5. Coleta tokens — aceita str, list ou None (usa ctx.tokens())
    if isinstance(result, str):
        tokens = [result]
    elif isinstance(result, (list, tuple)):
        tokens = [str(t) for t in result]
    else:
        tokens = ctx.tokens()

    if not tokens:
        raise TaskCodeError(
            "run() não retornou nenhum token de artifact. "
            "Use ctx.save_chart(), ctx.save_excel() ou ctx.save_pdf()."
        )

    return tokens


def default_test_range() -> tuple[str, str]:
    """Período padrão para testes: últimos 7 dias."""
    end   = date.today()
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat()
