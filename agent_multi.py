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
from datetime import datetime, timedelta
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


# ── Namespace persistente por sessão (estilo Jupyter) ─────────────────────────
# Cada sessão tem um dict de execução Python que persiste entre tool calls e
# entre invocações do sub-agente. O LLM recebe um resumo das variáveis ao final
# de cada tool para saber o que já está disponível para análises incrementais.

import pandas as pd
import numpy as np

_BUILTINS_SKIP = {"pd", "np", "__builtins__", "__doc__", "__name__", "__package__",
                  "__spec__", "__loader__", "__import__", "__build_class__"}

_namespaces: dict = {}       # session → namespace dict
_ns_last_access: dict = {}   # session → datetime do último acesso
_ns_lock = threading.Lock()


def _ns_get() -> dict:
    session = _current_session.get()
    with _ns_lock:
        if session not in _namespaces:
            _namespaces[session] = {"pd": pd, "np": np}
        _ns_last_access[session] = datetime.now()
        return _namespaces[session]


_MAX_RESULT_ROWS = 15  # acima disso, resultado de DataFrame é descrito, não exibido completo


def _df_describe(df: pd.DataFrame, nome: str = "result") -> str:
    """Descreve um DataFrame sem expor os dados completos ao LLM."""
    dtypes = ", ".join(f"{c}: {str(t)}" for c, t in df.dtypes.items())
    sample = df.head(1).to_markdown(index=False)
    return (
        f"`{nome}` — DataFrame com {len(df)} linhas e {len(df.columns)} colunas\n"
        f"Colunas e tipos: {dtypes}\n"
        f"Primeira linha de exemplo:\n{sample}"
    )


def _ns_summary(ns: dict) -> str:
    lines = []
    for k, v in ns.items():
        if k.startswith("_") or k in _BUILTINS_SKIP:
            continue
        if isinstance(v, pd.DataFrame):
            dtypes = ", ".join(f"{c}:{str(t)}" for c, t in v.dtypes.items())
            lines.append(f"  {k}: DataFrame — {len(v)} linhas | {dtypes}")
        elif isinstance(v, pd.Series):
            lines.append(f"  {k}: Series — {len(v)} elementos, dtype: {v.dtype}")
        elif isinstance(v, (int, float, bool)):
            lines.append(f"  {k} = {v}")
        elif isinstance(v, str):
            preview = v[:60].replace("\n", " ")
            lines.append(f"  {k} = '{preview}{'…' if len(v) > 60 else ''}'")
        else:
            lines.append(f"  {k}: {type(v).__name__}")
    if not lines:
        return "\n---\n_Ambiente vazio — nenhuma variável definida ainda._"
    return "\n---\n**Variáveis disponíveis no ambiente** (criadas em passos anteriores):\n" + "\n".join(lines)


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
    """Busca dados de uma API REST e injeta o DataFrame no ambiente de análise.

    O DataFrame fica disponível como variável com o nome da chave (ex: chave='producao'
    → variável `producao` no ambiente). Nunca retorna os dados ao LLM.

    Args:
        url: URL completa do endpoint (ex: 'http://localhost:8000/production').
        chave: Nome da variável no ambiente (ex: 'producao', 'defeitos').
        params: Parâmetros de query opcionais (ex: {"from": "2026-05-01", "to": "2026-05-15"}).
    """
    _tlog("chamar_api", "CHAMADA", url=url, chave=chave, params=params)
    try:
        response = http_requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(data) if isinstance(data, list) else pd.DataFrame([data])
        ns = _ns_get()
        ns[chave] = df
        msg = f"DataFrame '{chave}' injetado no ambiente: {len(df)} linhas, colunas: {list(df.columns)}."
        _tlog("chamar_api", "RETORNO", status="OK", linhas=len(df), colunas=list(df.columns))
    except http_requests.exceptions.HTTPError as e:
        msg = f"Erro HTTP {e.response.status_code}: {e.response.text}"
        _tlog("chamar_api", "RETORNO", status="ERRO", erro=msg)
        return msg
    except Exception as e:
        msg = f"Erro ao chamar API '{url}': {e}"
        _tlog("chamar_api", "RETORNO", status="ERRO", erro=msg)
        return msg
    return msg + _ns_summary(ns)


@tool
def analisar_dataframe(script: str) -> str:
    """Processa e analisa os dados disponíveis no ambiente, retornando o resultado formatado.

    Variáveis carregadas por chamar_api estão disponíveis pelo nome da chave.
    Variáveis criadas em chamadas anteriores desta tool também estão disponíveis.
    Atribua à variável `result` o que deve ser exibido — DataFrames são automaticamente
    convertidos para tabela markdown. Use print() para textos adicionais.

    Args:
        script: Lógica de análise a executar sobre os dados disponíveis.
    """
    _tlog("analisar_dataframe", "CHAMADA", script=script)

    ns = _ns_get()

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        exec(textwrap.dedent(script).lstrip("\n"), ns)
        console = sys.stdout.getvalue().strip()
        result = ns.get("result")

        parts = []
        if console:
            parts.append(f"```\n{console}\n```")
        if result is not None:
            if isinstance(result, pd.DataFrame):
                if len(result) <= _MAX_RESULT_ROWS:
                    parts.append(result.to_markdown(index=False))
                else:
                    parts.append(_df_describe(result))
            elif isinstance(result, pd.Series):
                if len(result) <= _MAX_RESULT_ROWS:
                    parts.append(result.to_frame().to_markdown())
                else:
                    parts.append(_df_describe(result.to_frame()))
            else:
                parts.append(str(result))
        if not parts:
            parts.append("Script executado (sem saída em `result`).")

        parts.append(_ns_summary(ns))
        saida = "\n\n".join(parts)
        _tlog("analisar_dataframe", "RETORNO", status="OK", saida=saida)
        return saida

    except Exception as e:
        msg = f"Erro:\n{type(e).__name__}: {e}\n\n{tb.format_exc()}"
        msg += _ns_summary(ns)
        _tlog("analisar_dataframe", "RETORNO", status="ERRO", erro=str(e))
        return msg
    finally:
        sys.stdout = old_stdout


@tool
def calcular_periodo(periodo: str) -> str:
    """Retorna as datas from/to em formato YYYY-MM-DD para um período em linguagem natural.

    Use esta tool ANTES de chamar_api sempre que precisar de um intervalo de datas.
    Nunca calcule datas manualmente.

    Args:
        periodo: Descrição do período desejado. Exemplos aceitos:
            'hoje', 'ontem', 'esta semana', 'semana passada',
            'ultimos 7 dias', 'ultimos 14 dias', 'ultimos 30 dias',
            'este mes', 'mes passado'.
    """
    _tlog("calcular_periodo", "CHAMADA", periodo=periodo)
    hoje = datetime.now().date()
    p = periodo.lower().strip()

    if p in ("hoje", "today"):
        frm = to = hoje
    elif p in ("ontem", "yesterday"):
        frm = to = hoje - timedelta(days=1)
    elif p in ("esta semana", "essa semana", "this week"):
        frm = hoje - timedelta(days=hoje.weekday())
        to = hoje
    elif p in ("semana passada", "last week"):
        start = hoje - timedelta(days=hoje.weekday() + 7)
        frm = start
        to = start + timedelta(days=6)
    elif p in ("este mes", "esse mes", "este mês", "esse mês", "this month"):
        frm = hoje.replace(day=1)
        to = hoje
    elif p in ("mes passado", "mês passado", "last month"):
        primeiro_deste = hoje.replace(day=1)
        to = primeiro_deste - timedelta(days=1)
        frm = to.replace(day=1)
    else:
        # Extrai número de dias de expressões como "ultimos 7 dias", "last 30 days"
        import re
        m = re.search(r"(\d+)", p)
        if m:
            days = int(m.group(1))
            frm = hoje - timedelta(days=days - 1)
            to = hoje
        else:
            msg = (
                f"Período '{periodo}' não reconhecido. "
                "Use: 'hoje', 'ontem', 'esta semana', 'semana passada', "
                "'ultimos N dias', 'este mes', 'mes passado'."
            )
            _tlog("calcular_periodo", "RETORNO", status="ERRO", msg=msg)
            return msg

    result = f"from={frm.isoformat()}&to={to.isoformat()}"
    _tlog("calcular_periodo", "RETORNO", status="OK", result=result)
    return result


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
        "  1. Chame read_skill() para obter a URL e estrutura dos dados.\n"
        "  2. Chame calcular_periodo() para obter as datas from/to corretas.\n"
        "  3. Chame chamar_api() usando os valores retornados por calcular_periodo.\n"
        "  4. Chame analisar_dataframe() para processar os dados e obter o resultado.\n"
        "     - Você pode chamar analisar_dataframe() várias vezes para análises em etapas.\n"
        "     - Variáveis criadas em chamadas anteriores de analisar_dataframe continuam disponíveis.\n"
        "  5. Só então redija a resposta final.\n\n"
        "## Regras\n"
        "- NUNCA responda com análises ou números sem antes concluir os passos 1 a 4.\n"
        "- NUNCA invente dados — use apenas resultados de analisar_dataframe.\n"
        "- Se analisar_dataframe retornar erro, corrija e chame novamente.\n"
        "- Formate SEMPRE a resposta final em markdown: use tabelas para dados tabulares, "
        "**negrito** para valores relevantes e listas quando apropriado.\n\n"
        f"## Skills disponíveis\n{catalogo}"
    )

    sub_tools = [read_skill, calcular_periodo, chamar_api, analisar_dataframe]
    llm_sub = llm.bind_tools(sub_tools)
    no_sub_tools = ToolNode(sub_tools)

    def no_sub_agente(state: State) -> dict:
        from langchain_core.messages import AIMessage as _AI
        msgs = [SystemMessage(content=SUB_SYSTEM_PROMPT)] + list(state["messages"])
        _tlog("sub_agente", "LLM INVOCADO", mensagens=len(msgs))
        response = llm_sub.invoke(msgs)

        meta = getattr(response, "response_metadata", {})
        finish = meta.get("finish_reason", "")

        if finish == "MALFORMED_FUNCTION_CALL":
            bad = meta.get("finish_message", "")
            _tlog("sub_agente", "MALFORMED_FUNCTION_CALL detectado", tentativa=bad)
            response = _AI(content=(
                "Erro interno: o modelo tentou computar datas em código Python em vez de "
                "chamar a tool `calcular_periodo`. Use calcular_periodo() para obter as "
                f"datas before/after e depois chame chamar_api normalmente.\n\n"
                f"Tentativa inválida capturada:\n```\n{bad}\n```"
            ))

        if os.getenv("DEBUG_TOOLS", "0").strip() == "1":
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
        config={"configurable": {"thread_id": _current_session.get()}, "recursion_limit": 15},
    )
    content = resultado["messages"][-1].content
    if not content or not content.strip():
        return (
            "O sub-agente analista não retornou nenhuma resposta. "
            "Isso geralmente indica uma falha interna ao processar a análise. "
            "Informe o usuário e sugira reformular a pergunta."
        )
    return content


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
    with _ns_lock:
        _namespaces.pop(session_id, None)
        _ns_last_access.pop(session_id, None)
    resultado = _orchestrator_graph.invoke(
        {"messages": [HumanMessage(content=query)]},
        config={"configurable": {"thread_id": session_id}, "recursion_limit": 20},
    )
    return resultado["messages"][-1].content



def is_multi_agent_ready() -> bool:
    return _orchestrator_graph is not None
