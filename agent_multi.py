"""
Multi-Agente LangGraph — Orquestrador + Sub-agente Analista de Gráficos
========================================================================
Arquitetura:

    Usuário
       ↓ query
    Orquestrador (StateGraph)
       ├─ get_current_datetime()     → responde data/hora direto
       └─ analisar_grafico(detalhes) → delega ao sub-agente
              └─ Sub-agente analista (StateGraph)
                    ├─ read_skill(filename) → lê instruções do arquivo .md
                    └─ chamar_api(url, params) → chama a API com os args da skill

O sub-agente recebe no system prompt o catálogo de skills disponíveis (headers dos .md).
Ele decide qual skill ler, lê as instruções, descobre qual API chamar e com quais params,
chama a API com chamar_api(), e por fim analisa o JSON retornado com o LLM.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import requests as http_requests
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

SKILLS_FOLDER = Path(__file__).parent / "skills"
SKILL_HEADER_LINES = 4

_orchestrator_graph = None
_sub_agent_graph = None


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
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


# ── Tools do sub-agente ───────────────────────────────────────────────────────

@tool
def read_skill(filename: str) -> str:
    """Lê o conteúdo completo de um arquivo de skill (.md) da pasta de skills.

    Use esta tool para obter as instruções detalhadas de como realizar
    um tipo específico de análise.

    Args:
        filename: Nome do arquivo .md (ex: 'analise_producao.md').
    """
    caminho = SKILLS_FOLDER / filename
    if not caminho.exists():
        arquivos = [f for f in os.listdir(SKILLS_FOLDER) if f.endswith(".md")]
        return (
            f"Arquivo '{filename}' não encontrado. "
            f"Skills disponíveis: {arquivos}"
        )
    return caminho.read_text(encoding="utf-8")


@tool
def chamar_api(url: str, params: Optional[dict] = None) -> str:
    """Faz uma requisição GET a uma URL de API e retorna o JSON resultante.

    Use esta tool para buscar dados externos conforme indicado pela skill.

    Args:
        url: URL completa do endpoint (ex: 'http://localhost:8000/production').
        params: Parâmetros de query opcionais
                (ex: {"from": "2026-05-01", "to": "2026-05-15"}).
    """
    try:
        response = http_requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        return json.dumps(response.json(), ensure_ascii=False)
    except http_requests.exceptions.HTTPError as e:
        return f"Erro HTTP {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Erro ao chamar API '{url}': {e}"


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

    SUB_SYSTEM_PROMPT = (
        "Você é um sub-agente especializado em análise de dados industriais.\n\n"
        "Você tem duas tools:\n"
        "- read_skill(filename): lê as instruções completas de como realizar uma análise.\n"
        "- chamar_api(url, params): chama uma API REST e retorna o JSON com os dados.\n\n"
        "Quando receber um pedido de análise, siga este processo:\n"
        "1. Identifique qual skill corresponde ao pedido usando o catálogo abaixo.\n"
        "2. Use read_skill(filename=...) para ler as instruções detalhadas.\n"
        "3. Siga as instruções da skill: use chamar_api() com a URL e params indicados.\n"
        "4. Analise o JSON retornado conforme as instruções e responda com a análise.\n\n"
        f"{catalogo}"
    )

    sub_tools = [read_skill, chamar_api]
    llm_sub = llm.bind_tools(sub_tools)
    no_sub_tools = ToolNode(sub_tools)

    def no_sub_agente(state: State) -> dict:
        msgs = [SystemMessage(content=SUB_SYSTEM_PROMPT)] + list(state["messages"])
        return {"messages": [llm_sub.invoke(msgs)]}

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

def _build_orchestrator(llm):
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
        msgs = [SystemMessage(content=ORQ_SYSTEM_PROMPT)] + list(state["messages"])
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

    return builder.compile()


# ── API pública ───────────────────────────────────────────────────────────────

def init_multi_agent(project: str, location: str, model_name: str) -> None:
    """Inicializa orquestrador e sub-agente. Chamado no startup do FastAPI."""
    global _orchestrator_graph, _sub_agent_graph
    try:
        from langchain_google_vertexai import ChatVertexAI
        llm = ChatVertexAI(
            model_name=model_name,
            project=project,
            location=location,
            temperature=0.7,
        )
        _sub_agent_graph = _build_sub_agent(llm)
        _orchestrator_graph = _build_orchestrator(llm)
        logger.info("Multi-agente inicializado: orquestrador + sub-agente analista")
    except Exception:
        import traceback
        logger.warning("Falha ao inicializar multi-agente:\n%s", traceback.format_exc())


def invoke_multi_agent(query: str) -> str:
    """Executa o orquestrador com a query do usuário e retorna a resposta final."""
    if _orchestrator_graph is None:
        raise RuntimeError("Multi-agente não inicializado.")
    resultado = _orchestrator_graph.invoke(
        {"messages": [HumanMessage(content=query)]},
        config={"recursion_limit": 20},
    )
    return resultado["messages"][-1].content


def is_multi_agent_ready() -> bool:
    return _orchestrator_graph is not None
