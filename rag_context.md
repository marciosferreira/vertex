# Contexto do Sistema MFG Control AI

## O que é este sistema
Plataforma de monitoramento industrial para uma fábrica de smartphones. Consolida dados de
produção, qualidade e status das linhas em tempo real, permitindo análises sob demanda
em linguagem natural.

## Linhas de produção e modelos

| Linha   | Modelo         |
|---------|----------------|
| Linha 1 | PhoneX Pro     |
| Linha 2 | PhoneX Lite    |
| Linha 3 | PhoneX Ultra   |
| Linha 4 | PhoneX Mini    |

Cada linha produz exclusivamente seu modelo. Filtrar por modelo é equivalente a filtrar pela linha.

## Turnos

| Turno | Horário         |
|-------|-----------------|
| A     | 06h às 13h      |
| B     | 14h às 21h      |
| C     | 22h às 05h      |

## Indicadores disponíveis

### Produção Diária vs Meta
Compara as unidades produzidas no dia com a meta planejada.
- **Produzido**: total de unidades finalizadas no dia
- **Meta (target)**: quantidade planejada para o dia
- Disponível por linha (line1–line4), por turno (A/B/C) ou agregado da fábrica
- Cores no gráfico: barra verde = dia que atingiu a meta, barra azul = abaixo da meta

### FPY — First Pass Yield
Percentual de unidades aprovadas na primeira inspeção, sem retrabalho.
- **FPY** = (unidades sem defeito / total produzido) × 100%
- Meta padrão: 95%. Abaixo disso é sinal de alerta.
- Disponível por turno e por modelo

### OEE — Overall Equipment Effectiveness
Indicador global de eficiência dos equipamentos. Composto por três fatores:
- **Disponibilidade**: tempo operando / tempo planejado — penalizado por paradas
- **Performance**: velocidade real / velocidade nominal — penalizado por micro-paradas e lentidão
- **OEE** = Disponibilidade × Performance × FPY (qualidade)
- Meta padrão: 85%. OEE classe mundial: ≥ 85%.
- Disponível por turno e por modelo

### Eficiência por Turno
Compara a eficiência (%) dos turnos A, B e C ao longo do tempo.
- Campos: shift_a_efficiency, shift_b_efficiency, shift_c_efficiency
- Para comparativo entre turnos, buscar sem filtro de turno — os três campos vêm preenchidos

### Produção por Hora (Perfil Intradiário)
Média de unidades produzidas por hora dentro de um turno, com desvio padrão.
- Identifica hora de pico, hora de menor rendimento e variabilidade
- Requer informar o turno (A, B ou C) — cada turno tem suas 8 horas

### Produção por Linha
Comparativo diário entre as quatro linhas (line1, line2, line3, line4).
- Gráfico de barras agrupadas ou empilhadas
- Permite identificar qual linha lidera ou está abaixo do esperado

### Status das Linhas (Tempo Real)
Snapshot atual de cada linha sem filtro de data.
- **status**: `running` (operando), `stopped` (parada), `maintenance` (em manutenção)
- Inclui: produzido até o momento, meta do dia, FPY atual, velocidade (speed_pct), operador responsável

### Defeitos por Categoria
Ranking e série temporal de defeitos por tipo.
- Categorias: `Tela (display)`, `Câmera`, `Bateria`, `Placa-mãe`, `Chassi / Carcaça`, `Conector USB`, `Outros`
- Gráfico padrão: Pareto (ranking + % acumulado)
- Pode filtrar por turno ou modelo
- Para série temporal de uma categoria específica, passar `category` na chamada

### Tendência de Defeitos
Evolução dos defeitos diários com regressão linear e média móvel.
- Indica se defeitos estão aumentando ou diminuindo e se a tendência é estatisticamente significativa
- Variante: taxa de defeitos (% sobre produção)
- Variante: projeção dos próximos N dias pela regressão

## Como interpretar os dados

- OEE baixo com disponibilidade alta mas performance baixa → micro-paradas ou lentidão operacional
- Produção abaixo da meta com OEE normal → problema de planejamento, não de equipamento
- FPY caindo com pico em uma categoria de defeito → investigar causa raiz naquela categoria
- Diferença de eficiência entre turnos estatisticamente significativa (ANOVA p<0.05) → investigar operador, setup ou condições do turno
- Linha com speed_pct < 100% mas status `running` → linha operando abaixo da capacidade nominal

## Granularidade dos dados
- Histórico: granularidade diária (um ponto por dia)
- Intradiário: granularidade horária (endpoint /production/hourly, requer turno)
- Status das linhas: snapshot em tempo real (endpoint /lines/status, sem filtro de data)
