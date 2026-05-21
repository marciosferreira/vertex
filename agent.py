"""
Agente LangGraph — Gemini via Vertex AI
========================================
Grafo ReAct simples: o LLM decide se usa alguma tool ou responde direto.
Tool disponível: get_current_datetime
"""

import logging
from datetime import datetime
from typing import Annotated

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

_agent_graph = None


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def get_current_datetime() -> str:
    """Retorna a data e hora atual do sistema.

    Use esta tool sempre que o usuário perguntar que horas são,
    qual é a data de hoje, ou qualquer variação dessas perguntas.
    """
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


# ── Grafo ────────────────────────────────────────────────────────────────────

class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _build_graph(llm):
    tools = [get_current_datetime]
    llm_com_tools = llm.bind_tools(tools)

    def no_agente(state: State) -> dict:
        resposta = llm_com_tools.invoke(state["messages"])
        return {"messages": [resposta]}

    def deve_usar_tool(state: State) -> str:
        ultima = state["messages"][-1]
        if hasattr(ultima, "tool_calls") and ultima.tool_calls:
            return "tools"
        return END

    no_tools = ToolNode(tools)

    builder = StateGraph(State)
    builder.add_node("agente", no_agente)
    builder.add_node("tools", no_tools)

    builder.add_edge(START, "agente")
    builder.add_conditional_edges("agente", deve_usar_tool, {"tools": "tools", END: END})
    builder.add_edge("tools", "agente")

    return builder.compile()


# ── API pública ───────────────────────────────────────────────────────────────

def init_agent(project: str, location: str, model_name: str, credentials=None) -> None:
    """Inicializa o grafo do agente. Chamado no startup do FastAPI."""
    global _agent_graph
    try:
        from langchain_google_vertexai import ChatVertexAI

        llm = ChatVertexAI(
            model_name=model_name,
            project=project,
            location=location,
            credentials=credentials,
            temperature=0.7,
        )
        _agent_graph = _build_graph(llm)
        logger.info("Agente LangGraph inicializado com modelo %s", model_name)
    except Exception:
        import traceback
        logger.warning("Falha ao inicializar agente LangGraph:\n%s", traceback.format_exc())


def invoke_agent(query: str) -> str:
    """Executa o agente com a query do usuário e retorna a resposta final."""
    if _agent_graph is None:
        raise RuntimeError("Agente não inicializado.")
    resultado = _agent_graph.invoke(
        {"messages": [HumanMessage(content=query)]}
    )
    return resultado["messages"][-1].content


def is_ready() -> bool:
    return _agent_graph is not None
