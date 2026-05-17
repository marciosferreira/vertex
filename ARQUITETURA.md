# Arquitetura Agêntica — MFG Control AI

---

## Um analista de dados sempre disponível

Imagine ter um analista de dados ou cientista de dados disponível a qualquer momento, capaz de acessar os dados reais da operação, criar gráficos, tabelas e análises customizadas na hora — e entregar uma resposta fundamentada em segundos.

É exatamente isso que esta arquitetura entrega. O gestor digita em linguagem natural — *"qual linha teve mais paradas esta semana e qual o impacto no OEE?"* — e o agente consulta APIs e banco de dados em tempo real, processa os dados e devolve a análise com gráfico, tabela ou relatório PDF. Sem espera, sem intermediário, sem dado inventado.

O que está documentado aqui é como isso foi construído para funcionar de forma robusta em ambiente industrial.

---

## A Arquitetura em uma frase

> Um **orquestrador** que interpreta o pedido em linguagem natural delega para um **sub-agente especialista** que consulta **APIs e banco de dados em tempo real**, analisa os dados em sandbox Python e entrega gráficos, tabelas ou PDFs — tudo transmitido ao vivo via **streaming SSE**, habilitando decisões rápidas e baseadas em informação.

---

## Grafo multi-agente (LangGraph)

A espinha dorsal é um grafo de estados (StateGraph) em dois níveis:

```text
Usuário
  └── Orquestrador (LangGraph)
        ├── get_current_datetime()   → responde diretamente
        ├── analisar_grafico()       → dispara o sub-agente
        └── gerar_pdf()              → empacota análise em PDF

              Sub-agente Analista (sub-grafo separado)
                ├── read_skill()         → lê instruções da skill
                ├── calcular_periodo()   → resolve datas em linguagem natural
                ├── chamar_api()         → busca dados via REST
                ├── executar_sql()       → queries ad-hoc no banco
                └── analisar_dataframe() → executa código Python/Pandas
```

O orquestrador **não sabe analisar dados** — ele só sabe a quem perguntar. O sub-agente **não tem acesso ao histórico de conversa** — ele só recebe o pedido pontual delegado. Essa separação de responsabilidades é deliberada: cada camada faz uma coisa e faz bem.

---

## Skills — documentação sob demanda

As skills são arquivos `.md` que descrevem como interagir com cada endpoint da API industrial. O sub-agente não recebe todo o conteúdo no startup — isso desperdiçaria contexto para skills que não serão usadas.

O que acontece de fato:

1. **Na inicialização**: apenas os cabeçalhos (primeiras 4 linhas de cada `.md`) são injetados no system prompt. O agente sabe que as skills existem e do que tratam.
2. **Sob demanda**: quando identifica qual skill precisa, chama `read_skill('nome.md')` e recebe o documento completo.

Isso é lazy-loading aplicado ao contexto do LLM. A consequência prática é que o sistema escala para dezenas de endpoints sem inflar o custo por token de cada requisição.

---

## Namespace persistente — o ambiente Jupyter do agente

O problema central de análise incremental: quando o agente chama `chamar_api()` e depois `analisar_dataframe()`, os DataFrames precisam estar disponíveis entre as chamadas. Mas tools em LangGraph rodam em threads separadas do `ThreadPoolExecutor` — `threading.local()` não funciona aqui.

A solução: um `dict` global indexado por `session_id`, protegido por `threading.Lock`, com o `session_id` atual propagado por `contextvars.ContextVar` (que, diferente de `threading.local()`, **se propaga automaticamente para threads filhas**).

O resultado é um ambiente de execução Python que se comporta exatamente como um notebook Jupyter:

- `chamar_api(url, chave='producao')` → injeta `df` como variável `producao` no namespace
- `analisar_dataframe(script)` → o script acessa `producao` diretamente, pode criar `resultado`, que fica disponível na próxima chamada
- Variáveis persistem entre múltiplas chamadas de tools e entre invocações consecutivas do sub-agente

---

## Proteção de contexto — o agente que não se afoga em dados

Um DataFrame com 30 dias de produção horária por linha pode ter milhares de linhas. Enviar isso para o modelo a cada tool call é caro, lento e desnecessário.

A regra implementada:

| Saída                | Condição      | O que o LLM recebe                          |
| -------------------- | ------------- | ------------------------------------------- |
| Tabela completa      | ≤ 15 linhas   | Markdown completo                           |
| Descrição estrutural | > 15 linhas   | shape + dtypes + primeira linha             |
| Resumo de namespace  | Sempre        | Metadados das variáveis (nome, tipo, shape) |
| Dados brutos         | Nunca         | — Protegido no backend                      |

O agente sempre sabe o que está disponível no ambiente (via `_ns_summary`) sem nunca receber os dados em si. Ele só vê dados quando o resultado da análise é pequeno o suficiente para ser relevante.

---

## Checkpointer — memória de conversa por sessão

O histórico de mensagens do orquestrador é persistido automaticamente pelo `SqliteSaver` do LangGraph no banco local. Cada `session_id` tem seu próprio thread de conversa — o usuário pode retomar uma análise horas depois e o agente lembra o contexto.

Para evitar que o contexto cresça indefinidamente (e o custo por token junto), o orquestrador envia ao modelo apenas as últimas `N` interações — o histórico completo fica no banco, mas o janela ativa é controlada.

---

## Streaming SSE — a interface que pensa em voz alta

O frontend não espera a resposta final. Cada etapa do processo chega em tempo real via **Server-Sent Events**:

```text
→ {"type": "thinking",  "text": "preciso verificar os dados de produção..."}
→ {"type": "tool",      "label": "📖 Lendo instruções da skill"}
→ {"type": "tool",      "label": "🌐 Buscando dados da API"}
→ {"type": "tool",      "label": "🔢 Processando e analisando dados"}
→ {"type": "reply",     "text": "## Produção Semanal\n\n![grafico](...)\n\n..."}
```

O desafio aqui é que o sub-agente roda dentro de um `@tool` do orquestrador — fora do stream principal do LangGraph. A solução é um **side-channel por sessão**: uma `queue.Queue` por `session_id` captura os eventos do sub-agente em tempo real e os entrega ao gerador SSE que está servindo o frontend.

---

## Gráficos e PDFs como artefatos persistentes

Quando o sub-agente gera um gráfico matplotlib, ele não trafega pelo contexto do LLM. O que acontece:

1. O script salva `result = fig` (figura matplotlib)
2. A tool serializa para PNG e armazena no banco com um UUID
3. O modelo recebe apenas o token `[chart:3f8a1b...]`
4. O FastAPI expõe `/chart/{id}` e o frontend renderiza a imagem

O mesmo padrão se aplica a PDFs gerados por `gerar_pdf()`. Os artefatos ficam disponíveis via URL enquanto a sessão estiver ativa — o banco funciona como object storage local.

---

## Por que isso importa para a sua fábrica

A combinação desses elementos resolve os problemas reais de quem quer colocar IA generativa num ambiente industrial:

| Problema | Solução nesta arquitetura |
| --- | --- |
| "O modelo inventa dados" | Sub-agente só responde com resultados de `analisar_dataframe` — sem dados, sem resposta |
| "A tela trava esperando a resposta" | Streaming SSE com thinking e tool calls em tempo real |
| "Não consigo analisar mês inteiro, é muita coisa" | Namespace incrementa análises em etapas, contexto protegido por limites de exibição |
| "O agente esquece o que foi dito antes" | Checkpointer SQLite persiste histórico por session_id |
| "Como adiciono novos endpoints sem mexer no agente?" | Basta criar um novo `.md` na pasta de skills |
| "O modelo fica confuso com muitas APIs ao mesmo tempo" | Lazy-loading de skills — só carrega o que vai usar |

---

## Stack

- **LLM**: Gemini 2.5 Flash (Google Vertex AI)
- **Orquestração**: LangGraph 1.0+ (StateGraph, ToolNode, SqliteSaver)
- **API**: FastAPI + SSE (sse-starlette)
- **Análise**: Python / Pandas / Matplotlib — sandbox via `exec()` em namespace isolado
- **Persistência**: SQLite (histórico de conversa + gráficos + PDFs na mesma base)
- **Threading**: `contextvars.ContextVar` para isolamento de sessão através de thread pools
