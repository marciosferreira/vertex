# Capacidades do agente — MFG Control AI

O MFG Control AI é um agente conversacional que responde em linguagem natural.

## Consultas pontuais (dados sob demanda)

O agente busca dados reais da API e os processa em tempo real. Exemplos:

- "Mostre a produção dos últimos 7 dias" → gráfico de barras com produção vs meta
- "Como está o FPY esta semana?" → gráfico de linha com tendência de FPY
- "Qual linha produziu mais no mês passado?" → comparativo entre Linha 1–4
- "Me dê uma tabela com produção e defeitos por dia" → tabela markdown com dados reais
- "Compare a eficiência dos turnos A, B e C" → barras agrupadas por turno
- "Qual a tendência de defeitos de câmera?" → gráfico de linha por categoria
- "Gere um relatório PDF da produção de maio" → PDF com gráficos e análise
- "Exporta os dados de OEE para Excel" → planilha .xlsx para download

Períodos aceitos em linguagem natural: "hoje", "ontem", "esta semana", "semana passada", "últimos N dias", "este mês", "mês passado".

## Perguntas conceituais

O agente responde sem buscar dados quando a pergunta é sobre definições ou cálculos:

- "O que é OEE?" / "Como o FPY é calculado?" / "O que significa downtime?"
- "Qual é a meta de FPY?" / "O que representa o turno C?"
- "Como interpretar um OEE abaixo de 85%?"

## Análise do dashboard atual

O agente pode descrever e interpretar o que está visível na tela naquele momento:

- "O que está mostrando no gráfico de produção agora?"
- "Quantos alertas ativos tem?"
- "Qual é o KPI de OEE que aparece no cabeçalho?"
- O usuário pode também enviar uma imagem (print do dashboard) para análise visual.

## Tarefas agendadas — relatórios e monitores automáticos

O agente pode criar tarefas que rodam automaticamente sem intervenção do usuário.

### Relatórios periódicos

- "Toda segunda às 8h me manda o relatório de produção semanal" → tarefa weekly
- "Todo dia às 7h gera um PDF com o resumo do dia anterior" → tarefa daily
- "Todo primeiro do mês exporta os dados de defeitos para Excel" → tarefa monthly

### Monitores com alertas

- "Me avise se a produção cair abaixo de 1000 unidades hoje" → monitor every_5m
- "Alerta se o OEE do turno A ficar abaixo de 80%" → monitor com threshold
- "Me notifique quando a Linha 1 ficar parada" → monitor de status

Frequências suportadas: `once`, `daily`, `weekly`, `monthly`, `every_Xm`, `every_Xh`, `every_Xd`.

Ao criar um monitor, o agente mostra o resultado do teste imediato e o threshold configurado.
Notificações aparecem como 🔔 no cabeçalho do dashboard.

### Gerenciamento de tarefas

- "Liste as tarefas agendadas" → mostra ID, nome, status e frequência
- "Pause a tarefa 003" / "Delete a tarefa 001" / "Edite a tarefa 002"
- "Editar tarefa 005" → o agente modifica o código, testa e salva automaticamente
