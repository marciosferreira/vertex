# Domínio industrial — MFG Control AI

## O que é este sistema

Plataforma de monitoramento industrial para uma fábrica de smartphones. Exibe indicadores
de produção, qualidade e status das linhas em tempo real, com análises sob demanda em
linguagem natural.

## Linhas de produção e modelos

A fábrica tem 4 linhas de produção. **Cada linha é o identificador estável** — o modelo que ela produz pode mudar ao longo do tempo.

| Linha   | Modelo atual (pode mudar)  |
|---------|----------------------------|
| Linha 1 | PhoneX Pro                 |
| Linha 2 | PhoneX Lite                |
| Linha 3 | PhoneX Ultra               |
| Linha 4 | PhoneX Mini                |

> Os modelos acima refletem a atribuição atual. Para saber o modelo vigente de cada linha, consulte `/lines` (retorna `id`, `name`, `model`).
>
> **Sempre filtre por linha (`line=1`, `line=2`, etc.), nunca por nome de modelo.** O nome do modelo é informação de contexto — o filtro correto e estável é o número da linha.

## Turnos

| Turno | Horário      |
|-------|--------------|
| A     | 06h às 13h   |
| B     | 14h às 21h   |
| C     | 22h às 05h   |

## KPIs do topo do dashboard

Exibidos no cabeçalho com filtros de período, turno e linha:

| KPI              | O que mostra                                                    |
|------------------|-----------------------------------------------------------------|
| Produzido        | Total de unidades no período + % atingida da meta               |
| First Pass Yield | FPY % do período com status OK ou Abaixo da meta (95%)          |
| Taxa de defeito  | % de unidades com defeito + contagens de scrap e retrabalho     |
| OEE              | Eficiência global % com referência à meta de 85%                |
| Downtime         | Minutos de paradas não planejadas no período                    |

## Painéis do dashboard

### Produção diária vs meta

Gráfico misto (barras + linha) mostrando volume diário de produção e defeitos contra a meta.

- **Produzido** (barras azuis): unidades finalizadas por dia
- **Defeitos** (barras vermelhas): unidades com defeito por dia
- **Meta** (linha tracejada cinza): meta diária planejada
- Filtros: período (7d/14d/30d/hoje), turno (Todos/A/B/C), linha

### First Pass Yield — histórico

Gráfico de linha mostrando a evolução do FPY ao longo do tempo.

- **FPY %** (linha verde com área sombreada): percentual de unidades aprovadas na primeira inspeção sem retrabalho
- **Meta** (linha tracejada vermelha, fixa em 95%): referência de qualidade
- FPY = (unidades sem defeito / total produzido) × 100%
- Eixo Y: de 85% a 100%
- Filtros: período, turno, linha

### Produção por linha — comparativo

Barras agrupadas comparando a produção diária entre as quatro linhas.

- **Linha 1 — PhoneX Pro** (azul)
- **Linha 2 — PhoneX Lite** (verde)
- **Linha 3 — PhoneX Ultra** (amarelo)
- **Linha 4 — PhoneX Mini** (roxo)
- Filtros: período, turno

### OEE — eficiência global

Gráfico de múltiplas linhas mostrando OEE e seus dois componentes mensuráveis.

- **OEE** (linha roxa sólida): eficiência global dos equipamentos
- **Disponib.** (linha verde tracejada): disponibilidade — tempo operando / tempo planejado
- **Perf.** (linha azul tracejada): performance — velocidade real / velocidade nominal
- OEE = Disponibilidade × Performance × FPY (qualidade)
- Eixo Y: de 65% a 100%
- Meta padrão: 85%. OEE ≥ 85% é considerado classe mundial.
- Filtros: período, turno, linha

### Status das linhas — AGORA

Painel em tempo real mostrando o estado atual de cada linha, sem filtro de data.

- **Status**: Rodando (verde) / Parada (vermelho) / Manutenção (amarelo)
- **Progresso**: barra de progresso com unidades produzidas até o momento vs meta do dia
- **FPY**: First Pass Yield atual da linha
- Exibe as quatro linhas com modelo e operador responsável

### Produção por hora

Gráfico misto com dois eixos Y mostrando o perfil intradiário de um turno.

- **Produção** (barras azuis, eixo esquerdo): média de unidades produzidas por hora com barras de erro ±1 desvio padrão
- **Meta/hora** (linha tracejada cinza, eixo esquerdo): meta média por hora
- **Defeitos** (barras vermelhas, eixo direito): média de defeitos por hora com barras de erro ±1 desvio padrão
- Turno é obrigatório (A, B ou C) — cada turno cobre 8 horas
- Filtros: período, turno (obrigatório), modelo

### Eficiência por turno

Barras agrupadas comparando a eficiência dos três turnos ao longo do período.

- **Turno A** (barras azuis)
- **Turno B** (barras verdes)
- **Turno C** (barras roxas)
- Eixo Y: de 65% a 100%
- Filtros: período, linha

### Defeitos por categoria

Barras horizontais mostrando o volume de defeitos por tipo no período.

- Categorias: Tela (display), Câmera, Bateria, Placa-mãe, Chassi / Carcaça, Conector USB, Outros
- Cada categoria tem uma cor fixa (vermelho, laranja, roxo, azul, verde, amarelo, cinza)
- Filtros: período, turno, linha

### Tendência de defeitos

Gráfico de múltiplas linhas mostrando a evolução diária de cada categoria de defeito.

- **Tela** (linha vermelha sólida): defeitos de tela por dia
- **Câmera** (linha laranja tracejada): defeitos de câmera por dia
- **Bateria** (linha roxa tracejada): defeitos de bateria por dia
- **Outros** (linha verde sólida): demais defeitos por dia
- Filtros: período, turno, linha

## Como interpretar os dados

- OEE baixo com Disponib. alta mas Perf. baixa → micro-paradas ou lentidão operacional, não falhas de equipamento
- Produção abaixo da meta com OEE normal → problema de planejamento ou capacidade, não de equipamento
- FPY caindo com linha crescente no gráfico de tendência de defeitos → investigar a categoria que está subindo
- Diferença de eficiência entre turnos → investigar operador, setup ou condições específicas do turno
- Linha com progresso baixo no painel de status com status "Rodando" → linha operando abaixo da velocidade nominal
- Downtime alto com Disponib. baixa no OEE → paradas não planejadas impactando a produção

## Granularidade dos dados

- Histórico: granularidade diária (um ponto por dia)
- Intradiário: granularidade horária — disponível apenas no painel "Produção por hora", requer turno
- Status das linhas: snapshot em tempo real, sem filtro de data
