# Arquitetura do sistema de agentes — MFG Control AI

O sistema usa um grafo multi-agente LangGraph com três agentes cooperando.

## Orquestrador

Nó central que recebe todas as mensagens do usuário e decide como rotear:

| Tipo de pedido                                         | Roteamento                                        |
|--------------------------------------------------------|---------------------------------------------------|
| Consulta de dados (gráfico, tabela, relatório)         | `calcular_periodo()` → `consultar_analista()`     |
| Pergunta conceitual (o que é X, como se calcula Y)     | tools `rag_*()` → responde direto                 |
| Dashboard atual (o que aparece na tela, KPIs, alertas) | `get_dashboard_charts()`                          |
| Agendamento (criar, editar, listar, pausar, deletar)   | `gerenciar_agenda()`                              |
| Pergunta simples (data, hora, saudação)                | responde direto                                   |

O orquestrador mantém histórico completo da sessão via checkpointer SQLite — nunca perde
o contexto de conversas anteriores dentro da mesma sessão.

Após qualquer ação de edição de código (`get_task_code`), um nó guardião verifica
automaticamente se `save_task_code` foi chamado. Se não, injeta uma correção forçando
o orquestrador a completar o fluxo.

## Sub-agente analista

Ativado pelo orquestrador via `consultar_analista()`. Executa análises em quatro etapas obrigatórias:

1. `read_skill(filename)` — lê as instruções da skill correta para o tipo de análise
2. `calcular_periodo()` + `chamar_api()` — busca dados da API REST e os injeta como DataFrame
   no ambiente (os dados **não** passam pelo LLM — ficam em memória)
3. `analisar_dataframe(script)` — executa código Python/Pandas, podendo gerar gráfico
   (`result = fig`) ou tabela (`result = df`)
4. Redige a resposta final com os resultados reais

O ambiente de execução persiste entre chamadas na mesma sessão (estilo Jupyter) —
DataFrames criados em um passo ficam disponíveis nos passos seguintes.

Para análises que a API não cobre diretamente (JOINs, rankings, cruzamentos), o sub-agente
usa `executar_sql()` com queries SELECT direto no banco SQLite.

### Skills disponíveis para o sub-agente

| Arquivo                     | O que cobre                                                      |
|-----------------------------|------------------------------------------------------------------|
| `analise_producao.md`       | Produção diária vs meta, FPY, OEE, defeitos por linha e turno   |
| `analise_sql_livre.md`      | Análise ad-hoc via SQL — qualquer consulta que a API não oferece |
| `defeitos_por_categoria.md` | Volume de defeitos por categoria no período                      |
| `eficiencia_por_turno.md`   | Comparativo de eficiência entre turnos A, B e C                  |
| `fpy_historico.md`          | Histórico de First Pass Yield ao longo do tempo                  |
| `oee_historico.md`          | Histórico de OEE e seus componentes (disponibilidade, performance)|
| `producao_diaria_vs_meta.md`| Produção diária comparada à meta planejada                       |
| `producao_por_hora.md`      | Perfil intradiário hora a hora (requer turno)                    |
| `producao_por_linha.md`     | Produção comparativa entre as quatro linhas                      |
| `status_linhas.md`          | Status em tempo real de cada linha                               |
| `tendencia_defeitos.md`     | Evolução diária de defeitos por categoria                        |

## Sub-agente de scheduling

Ativado pelo orquestrador via `gerenciar_agenda()`. Responsável exclusivamente por
operações em tarefas agendadas: criar, listar, editar, pausar, deletar, salvar e testar código.

Cada tarefa pode executar em dois modos:

- **Modo LLM**: o daemon usa as `instructions` da tarefa para montar um prompt e chama o agente normalmente
- **Modo determinístico** (com `task_code`): executa `def run(from_date, to_date, ctx)` diretamente,
  sem LLM — mais rápido e sem custo de inferência

O objeto `ctx` injetado no `run()` oferece:

| Método                              | O que faz                                          |
|-------------------------------------|----------------------------------------------------|
| `ctx.api(url)`                      | Chama um endpoint REST e retorna os dados como list |
| `ctx.today()`                       | Retorna a data atual no formato `YYYY-MM-DD`        |
| `ctx.date_range(days=N)`            | Retorna `(from_date, to_date)` para os últimos N dias|
| `ctx.save_chart(fig)`               | Salva figura matplotlib e retorna token `[chart:uuid]`|
| `ctx.generate_pdf(titulo, conteudo)`| Gera PDF e retorna token `[pdf:uuid]`              |
| `ctx.generate_excel(df, nome)`      | Gera Excel e retorna token `[excel:uuid]`          |
| `ctx.notify(msg, value, threshold)` | Dispara notificação 🔔 no dashboard                |
