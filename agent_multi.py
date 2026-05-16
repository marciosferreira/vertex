"""
Multi-Agente LangGraph — Orquestrador + Sub-agente Analista de Dados
========================================================================
Arquitetura:

    Usuário
       ↓ query
    Orquestrador (StateGraph)
       ├─ get_current_datetime()     → responde data/hora direto
       └─ analisar_grafico(detalhes) → delega ao sub-agente
              └─ Sub-agente analista (StateGraph)
                    ├─ read_skill(filename)              → lê instruções do arquivo .md
                    ├─ chamar_api(url, params)            → chama a API REST
                    └─ executar_codigo_pandas(codigo, chave) → sandbox Python/Pandas

Fluxo do sub-agente por análise:
  1. read_skill → descobre a API e a estrutura do JSON
  2. chamar_api(url, chave) → busca dados e salva JSON em api_data[chave] (sem expor ao LLM)
  3. executar_codigo_pandas(codigo, chave) → cria df, analisa, retorna resultado formatado
"""

import contextvars
import io
import logging
import os
import sqlite3
import sys
import textwrap
import threading
import traceback as tb
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests as http_requests
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import Annotated, TypedDict

logger = logging.getLogger(__name__)

SKILLS_FOLDER = Path(__file__).parent / "skills"
SKILL_HEADER_LINES = 4
DB_PATH = Path(__file__).parent / "mfg.db"

_orchestrator_graph = None
_sub_agent_graph = None
_checkpointer = None

# Propaga o session_id através das fronteiras de thread do ToolNode.
# contextvars.ContextVar se propaga para threads criadas por ThreadPoolExecutor,
# que é o que o ToolNode do LangGraph usa internamente.
_current_session: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mfg_session", default="default"
)



def _tlog(tool: str, event: str, **kwargs) -> None:
    """Loga chamadas e saídas de tools quando DEBUG_TOOLS=1."""
    if os.getenv("DEBUG_TOOLS", "0").strip() != "1":
        return
    lines = [f"\n{'='*60}", f"[TOOL] {tool} | {event}"]
    truncate = int(os.getenv("DEBUG_TOOLS_TRUNCATE", "0"))
    for k, v in kwargs.items():
        text = str(v)
        if truncate > 0 and len(text) > truncate:
            text = text[:truncate] + " …(truncado)"
        lines.append(f"  {k}: {text}")
    lines.append("="*60)
    logger.info("\n".join(lines))


# ── Store de DataFrames compartilhado entre threads ───────────────────────────
# dict global + Lock: todas as threads leem/escrevem no mesmo store.
# contextvars.ContextVar isola por session — o ContextVar se propaga para threads
# criadas por ThreadPoolExecutor (usado pelo ToolNode), resolvendo o bug do
# threading.local() que dava store vazio na segunda tool call.

_df_store: dict = {}
_df_lock = threading.Lock()


def _df_set(chave: str, df) -> None:
    key = f"{_current_session.get()}:{chave}"
    with _df_lock:
        _df_store[key] = df


def _df_get(chave: str):
    key = f"{_current_session.get()}:{chave}"
    with _df_lock:
        return _df_store.get(key)


def _df_list() -> list[str]:
    prefix = f"{_current_session.get()}:"
    with _df_lock:
        return [k.removeprefix(prefix) for k in _df_store if k.startswith(prefix)]


# ── Estado compartilhado ──────────────────────────────────────────────────────

class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ── Tools do orquestrador ─────────────────────────────────────────────────────

@tool
def get_current_datetime() -> str:
    """Retorna a data e hora atual do sistema.

    Use esta tool sempre que o usuário perguntar que horas são,
    qual é a data de hoje, ou qualquer variação dessas perguntas.
    """
    result = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    _tlog("get_current_datetime", "RETORNO", resultado=result)
    return result


# ── Tools do sub-agente ───────────────────────────────────────────────────────

@tool
def read_skill(filename: str) -> str:
    """Lê o conteúdo completo de um arquivo de skill (.md) da pasta de skills.

    Use esta tool para obter as instruções detalhadas de como realizar
    um tipo específico de análise.

    Args:
        filename: Nome do arquivo .md (ex: 'analise_producao.md').
    """
    _tlog("read_skill", "CHAMADA", filename=filename)
    caminho = SKILLS_FOLDER / filename
    if not caminho.exists():
        arquivos = [f for f in os.listdir(SKILLS_FOLDER) if f.endswith(".md")]
        msg = f"Arquivo '{filename}' não encontrado. Skills disponíveis: {arquivos}"
        _tlog("read_skill", "RETORNO", resultado=msg)
        return msg
    conteudo = caminho.read_text(encoding="utf-8")
    _tlog("read_skill", "RETORNO", chars=len(conteudo), conteudo=conteudo)
    return conteudo


@tool
def chamar_api(url: str, chave: str, params: Optional[dict] = None) -> str:
    """Busca dados de uma API REST, converte para DataFrame e armazena para análise.

    O DataFrame fica disponível para executar_codigo_pandas(chave=...) como variável `df`.
    Nunca retorna os dados ao LLM — apenas confirmação de sucesso ou erro.

    Args:
        url: URL completa do endpoint (ex: 'http://localhost:8000/production').
        chave: Nome da chave para identificar os dados (ex: 'producao', 'defeitos').
        params: Parâmetros de query opcionais (ex: {"from": "2026-05-01", "to": "2026-05-15"}).
    """
    import pandas as pd
    _tlog("chamar_api", "CHAMADA", url=url, chave=chave, params=params)
    try:
        response = http_requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(data) if isinstance(data, list) else pd.DataFrame([data])
        _df_set(chave, df)
        msg = f"DataFrame salvo na chave '{chave}': {len(df)} linhas, colunas: {list(df.columns)}."
        _tlog("chamar_api", "RETORNO", status="OK", linhas=len(df), colunas=list(df.columns))
    except http_requests.exceptions.HTTPError as e:
        msg = f"Erro HTTP {e.response.status_code}: {e.response.text}"
        _tlog("chamar_api", "RETORNO", status="ERRO", erro=msg)
    except Exception as e:
        msg = f"Erro ao chamar API '{url}': {e}"
        _tlog("chamar_api", "RETORNO", status="ERRO", erro=msg)
    return msg


@tool
def analisar_dataframe(script: str, chave: str) -> str:
    """Processa e analisa os dados buscados por chamar_api, retornando o resultado formatado.

    O DataFrame fica disponível como variável `df`. Atribua o resultado à variável
    `result` para formatação automática em markdown. Use print() para textos adicionais.

    Args:
        script: Lógica de análise a executar sobre o DataFrame `df`.
        chave: Mesma chave usada em chamar_api (ex: 'producao').
    """
    import pandas as pd
    import numpy as np

    _tlog("analisar_dataframe", "CHAMADA", chave=chave, script=script)

    df = _df_get(chave)
    if df is None:
        disponiveis = _df_list()
        msg = f"Chave '{chave}' não encontrada. Disponíveis: {disponiveis}. Chame chamar_api primeiro."
        _tlog("analisar_dataframe", "RETORNO", status="ERRO", erro=msg)
        return msg

    if not isinstance(df, pd.DataFrame):
        msg = f"Dado em '{chave}' não é um DataFrame (tipo: {type(df).__name__}). Chame chamar_api primeiro."
        _tlog("analisar_dataframe", "RETORNO", status="ERRO", erro=msg)
        return msg

    _tlog("analisar_dataframe", "SANDBOX", linhas=len(df), colunas=list(df.columns))

    exec_globals = {"pd": pd, "np": np, "df": df}

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        exec(textwrap.dedent(script).lstrip("\n"), exec_globals)
        console = sys.stdout.getvalue().strip()
        result = exec_globals.get("result")

        parts = []
        if console:
            parts.append(f"```\n{console}\n```")
        if result is not None:
            if isinstance(result, pd.DataFrame):
                parts.append(result.to_markdown())
            elif isinstance(result, pd.Series):
                parts.append(result.to_frame().to_markdown())
            else:
                parts.append(str(result))
        if not parts:
            parts.append("Análise concluída (sem saída).")

        cols = ", ".join(str(c) for c in df.columns[:20])
        parts.append(f"\n_Colunas disponíveis em `df`: {cols}_")
        saida = "\n\n".join(parts)
        _tlog("analisar_dataframe", "RETORNO", status="OK", console=console or "(vazio)", saida=saida)
        return saida

    except Exception as e:
        extra = ""
        if isinstance(e, KeyError):
            cols = ", ".join(str(c) for c in df.columns)
            extra = f"\n\nColunas disponíveis: {cols}"
        msg = f"Erro:\n{type(e).__name__}: {e}{extra}\n\n{tb.format_exc()}"
        _tlog("analisar_dataframe", "RETORNO", status="ERRO", erro=str(e))
        return msg
    finally:
        sys.stdout = old_stdout


# ── Catálogo de skills (injetado no system prompt do sub-agente) ──────────────

def _montar_catalogo_skills() -> str:
    """Lê os headers dos arquivos .md e monta o texto de catálogo para o system prompt."""
    try:
        arquivos = sorted(f for f in os.listdir(SKILLS_FOLDER) if f.endswith(".md"))
    except FileNotFoundError:
        return "Nenhuma skill disponível."
    if not arquivos:
        return "Nenhuma skill disponível."

    linhas = ["Skills disponíveis (use read_skill para ver as instruções completas):\n"]
    for arq in arquivos:
        caminho = SKILLS_FOLDER / arq
        with open(caminho, encoding="utf-8") as f:
            header = "".join(f.readline() for _ in range(SKILL_HEADER_LINES))
        linhas.append(f"  Arquivo: {arq}\n{header.strip()}\n")

    return "\n".join(linhas)


# ── Sub-agente analista ───────────────────────────────────────────────────────

def _build_sub_agent(llm):
    catalogo = _montar_catalogo_skills()

    hoje = datetime.now().strftime("%d/%m/%Y")

    SUB_SYSTEM_PROMPT = (
        f"Data de hoje: {hoje}\n\n"
        "Você é um sub-agente especializado em análise de dados industriais.\n\n"
        "## Fluxo obrigatório\n"
        "Para QUALQUER pedido de análise, siga estes passos nesta ordem:\n"
        "  1. Chame read_skill() com o arquivo da skill correspondente ao pedido.\n"
        "  2. Chame chamar_api() conforme indicado pela skill para buscar os dados.\n"
        "  3. Chame analisar_dataframe() com script Pandas adequado ao pedido do usuário.\n"
        "  4. Só então redija a resposta final com base no resultado retornado pelo sandbox.\n\n"
        "## Regras\n"
        "- NUNCA responda com análises ou números sem antes concluir os passos 1, 2 e 3.\n"
        "- NUNCA invente dados — use apenas o resultado de analisar_dataframe.\n"
        "- Se analisar_dataframe retornar erro, corrija o script e execute novamente.\n\n"
        f"## Skills disponíveis\n{catalogo}"
    )

    sub_tools = [read_skill, chamar_api, analisar_dataframe]
    llm_sub = llm.bind_tools(sub_tools)
    no_sub_tools = ToolNode(sub_tools)

    def no_sub_agente(state: State) -> dict:
        msgs = [SystemMessage(content=SUB_SYSTEM_PROMPT)] + list(state["messages"])
        _tlog("sub_agente", "LLM INVOCADO", mensagens=len(msgs))
        response = llm_sub.invoke(msgs)

        if os.getenv("DEBUG_TOOLS", "0").strip() == "1":
            meta = getattr(response, "response_metadata", {})
            if hasattr(response, "tool_calls") and response.tool_calls:
                nomes = [tc["name"] for tc in response.tool_calls]
                logger.info(f"\n[SUB-AGENTE] → tool calls: {nomes}")
            else:
                logger.info(
                    f"\n[SUB-AGENTE] → SEM tool call"
                    f"\n  type       : {type(response).__name__}"
                    f"\n  content    : {repr(response.content)}"
                    f"\n  tool_calls : {getattr(response, 'tool_calls', 'N/A')}"
                    f"\n  add_kwargs : {getattr(response, 'additional_kwargs', {})}"
                    f"\n  response_metadata: {meta}"
                )
        return {"messages": [response]}

    def sub_para_onde(state: State) -> str:
        ultima = state["messages"][-1]
        if hasattr(ultima, "tool_calls") and ultima.tool_calls:
            return "tools"
        return END

    builder = StateGraph(State)
    builder.add_node("sub_agente", no_sub_agente)
    builder.add_node("tools", no_sub_tools)
    builder.add_edge(START, "sub_agente")
    builder.add_conditional_edges("sub_agente", sub_para_onde, {"tools": "tools", END: END})
    builder.add_edge("tools", "sub_agente")

    return builder.compile()


# ── Tool do orquestrador que dispara o sub-agente ────────────────────────────

@tool
def analisar_grafico(detalhes: str) -> str:
    """Delega a análise de um gráfico ao sub-agente especialista.

    O sub-agente irá identificar a skill correta, buscar os dados na API
    e retornar uma análise baseada nos dados reais.

    Args:
        detalhes: O que o usuário quer analisar (ex: "produção diária desta semana",
                  "produção vs meta dos últimos 14 dias").
    """
    if _sub_agent_graph is None:
        return "Sub-agente analista não inicializado."
    resultado = _sub_agent_graph.invoke(
        {"messages": [HumanMessage(content=detalhes)]},
        config={"recursion_limit": 15},
    )
    return resultado["messages"][-1].content


# ── Orquestrador ──────────────────────────────────────────────────────────────

MAX_INTERACOES = int(os.getenv("MAX_INTERACOES", "10"))


def _build_orchestrator(llm, checkpointer=None):
    ORQ_SYSTEM_PROMPT = (
        "Você é o agente orquestrador de um sistema de monitoramento industrial.\n\n"
        "Você tem duas tools:\n"
        "- get_current_datetime(): use quando o usuário perguntar data ou hora.\n"
        "- analisar_grafico(detalhes): use quando o usuário pedir análise de dados, "
        "gráficos ou relatórios de produção. O sub-agente especialista irá buscar "
        "os dados reais e retornar a análise.\n\n"
        "Para perguntas que não exigem nenhuma dessas tools, responda diretamente."
    )

    orq_tools = [get_current_datetime, analisar_grafico]
    llm_orq = llm.bind_tools(orq_tools)
    no_orq_tools = ToolNode(orq_tools)

    def no_orquestrador(state: State) -> dict:
        # Limita o contexto enviado ao LLM às últimas MAX_INTERACOES interações.
        # O checkpointer continua guardando o histórico completo no banco.
        historico_recente = state["messages"][-(MAX_INTERACOES * 2):]
        msgs = [SystemMessage(content=ORQ_SYSTEM_PROMPT)] + historico_recente
        return {"messages": [llm_orq.invoke(msgs)]}

    def orq_para_onde(state: State) -> str:
        ultima = state["messages"][-1]
        if hasattr(ultima, "tool_calls") and ultima.tool_calls:
            return "tools"
        return END

    builder = StateGraph(State)
    builder.add_node("orquestrador", no_orquestrador)
    builder.add_node("tools", no_orq_tools)
    builder.add_edge(START, "orquestrador")
    builder.add_conditional_edges("orquestrador", orq_para_onde, {"tools": "tools", END: END})
    builder.add_edge("tools", "orquestrador")

    return builder.compile(checkpointer=checkpointer)


# ── API pública ───────────────────────────────────────────────────────────────

def init_multi_agent(project: str, location: str, model_name: str) -> None:
    """Inicializa orquestrador e sub-agente. Chamado no startup do FastAPI."""
    global _orchestrator_graph, _sub_agent_graph, _checkpointer
    try:
        from langchain_google_vertexai import ChatVertexAI
        from langgraph.checkpoint.sqlite import SqliteSaver

        llm = ChatVertexAI(
            model_name=model_name,
            project=project,
            location=location,
            temperature=0.7,
        )

        # Conexão persistente para o checkpointer (check_same_thread=False pois
        # o FastAPI despacha requests em threads diferentes)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _checkpointer = SqliteSaver(conn)

        _sub_agent_graph = _build_sub_agent(llm)
        _orchestrator_graph = _build_orchestrator(llm, _checkpointer)
        logger.info("Multi-agente inicializado: orquestrador + sub-agente analista")
    except Exception:
        import traceback
        logger.warning("Falha ao inicializar multi-agente:\n%s", traceback.format_exc())


def invoke_multi_agent(query: str, session_id: str = "default") -> str:
    """Executa o orquestrador com a query do usuário e retorna a resposta final.

    O session_id isola o histórico de conversa — cada sessão tem seu próprio contexto
    persistido no mfg.db via SqliteSaver, e seus DataFrames no store em memória.
    """
    if _orchestrator_graph is None:
        raise RuntimeError("Multi-agente não inicializado.")
    _current_session.set(session_id)
    resultado = _orchestrator_graph.invoke(
        {"messages": [HumanMessage(content=query)]},
        config={"configurable": {"thread_id": session_id}, "recursion_limit": 20},
    )
    return resultado["messages"][-1].content


def is_multi_agent_ready() -> bool:
    return _orchestrator_graph is not None
