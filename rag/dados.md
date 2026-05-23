# API REST e schema do banco — MFG Control AI

## API REST — endpoints e filtros

Todos os endpoints aceitam os seguintes filtros opcionais via query string:

| Parâmetro | Formato        | Descrição                                              |
|-----------|----------------|--------------------------------------------------------|
| `from`    | `YYYY-MM-DD`   | Data inicial do período                                |
| `to`      | `YYYY-MM-DD`   | Data final do período                                  |
| `shift`   | `A`, `B` ou `C`| Filtra por turno (omitir = todos os turnos agregados)  |
| `line`    | `1`, `2`, `3` ou `4` | Filtra por linha de produção                    |

O filtro correto é sempre `line=<número>`. O nome do modelo associado a cada linha pode mudar; para descobrir o modelo atual de cada linha, use `GET /lines`.

### Endpoints principais

| Método | Endpoint                  | Descrição                                                           |
|--------|---------------------------|---------------------------------------------------------------------|
| GET    | `/lines`                  | Linhas de produção com modelo atual (`id`, `name`, `model`)         |
| GET    | `/production/historical`  | Dados históricos diários: produção, defeitos, FPY, OEE, eficiência  |
| GET    | `/production/hourly`      | Produção hora a hora — requer `shift`                               |
| GET    | `/lines/status`           | Status em tempo real das quatro linhas                              |
| GET    | `/defects`                | Defeitos por categoria no período                                   |
| GET    | `/kpis`                   | KPIs do turno atual (produzido, FPY, OEE, downtime)                 |
| GET    | `/alerts`                 | Alertas registrados com severidade e linha                          |

## Schema do banco de dados

O banco é SQLite (`mfg.db`). Tabelas disponíveis para queries SQL via `executar_sql`.

### `production` — produção granular

Uma linha por (date, shift, line, model).

| Coluna   | Tipo    | Descrição                                                              |
|----------|---------|------------------------------------------------------------------------|
| date     | TEXT    | Data ISO `YYYY-MM-DD`                                                  |
| shift    | TEXT    | Turno: `A`, `B` ou `C`                                                 |
| line     | INTEGER | Linha: 1–4                                                             |
| model    | TEXT    | `PhoneX Pro`, `PhoneX Lite`, `PhoneX Ultra`, `PhoneX Mini`             |
| produced | INTEGER | Unidades produzidas                                                    |
| target   | INTEGER | Meta de produção                                                       |

### `defects` — defeitos granulares

Uma linha por (date, shift, line, category).

| Coluna   | Tipo    | Descrição                                                                                     |
|----------|---------|-----------------------------------------------------------------------------------------------|
| date     | TEXT    | Data ISO `YYYY-MM-DD`                                                                         |
| shift    | TEXT    | Turno: `A`, `B` ou `C`                                                                        |
| line     | INTEGER | Linha: 1–4                                                                                    |
| category | TEXT    | `Tela (display)`, `Câmera`, `Bateria`, `Placa-mãe`, `Chassi / Carcaça`, `Conector USB`, `Outros` |
| count    | INTEGER | Quantidade de defeitos                                                                        |

### `metrics` — métricas diárias consolidadas

Uma linha por dia (date único).

| Coluna                                                   | Tipo    | Descrição                      |
|----------------------------------------------------------|---------|--------------------------------|
| date                                                     | TEXT    | Data ISO `YYYY-MM-DD`          |
| fpy_a / fpy_b / fpy_c                                    | REAL    | FPY por turno (%)              |
| oee_a / oee_b / oee_c                                    | REAL    | OEE por turno (%)              |
| availability                                             | REAL    | Disponibilidade OEE (%)        |
| performance                                              | REAL    | Performance OEE (%)            |
| shift_a_efficiency / shift_b_efficiency / shift_c_efficiency | INTEGER | Eficiência por turno (%)  |

### `hourly_production` — produção hora a hora

Uma linha por (date, shift, line, model, hour).

| Coluna   | Tipo    | Descrição                                         |
|----------|---------|---------------------------------------------------|
| hour     | TEXT    | Formato `06h`, `07h`, …, `05h`                    |
| produced | INTEGER | Unidades produzidas na hora                       |
| target   | INTEGER | Meta horária                                      |
| defects  | INTEGER | Defeitos na hora                                  |

### `lines_status` — estado atual das linhas

Snapshot estático (sem histórico). Status em inglês: `running`, `stopped`, `maintenance`.

| Coluna    | Tipo    | Descrição                         |
|-----------|---------|-----------------------------------|
| id        | INTEGER | Linha (1–4)                       |
| name      | TEXT    | Nome (`Linha 1`, …, `Linha 4`)    |
| model     | TEXT    | Modelo sendo produzido            |
| status    | TEXT    | `running`, `stopped`, `maintenance`|
| produced  | INTEGER | Produção acumulada do dia         |
| target    | INTEGER | Meta diária                       |
| fpy       | REAL    | FPY atual (%)                     |
| speed_pct | INTEGER | Velocidade em % da capacidade     |
| operator  | TEXT    | Operador responsável              |

### `alerts` — alertas registrados

| Coluna       | Tipo    | Descrição                                 |
|--------------|---------|-------------------------------------------|
| datetime     | TEXT    | `YYYY-MM-DDTHH:MM:SS`                     |
| severity     | TEXT    | `critical`, `warning`, `info`             |
| line         | INTEGER | Linha relacionada (1–4)                   |
| message      | TEXT    | Descrição do alerta                       |
| acknowledged | INTEGER | `0` = não reconhecido, `1` = reconhecido  |

### `kpis` — KPIs por turno

Uma linha por turno (A/B/C).

| Coluna             | Tipo    | Descrição                      |
|--------------------|---------|--------------------------------|
| shift              | TEXT    | PK: `A`, `B` ou `C`            |
| total_produced     | INTEGER | Total produzido no turno       |
| daily_target       | INTEGER | Meta do turno                  |
| first_pass_yield   | REAL    | FPY (%)                        |
| defect_rate        | REAL    | Taxa de defeito (%)            |
| downtime_minutes   | INTEGER | Tempo de parada (minutos)      |
| efficiency         | REAL    | Eficiência (%)                 |
| scrapped           | INTEGER | Unidades descartadas           |
| reworked           | INTEGER | Unidades retrabalhadas         |
| cycle_time_seconds | REAL    | Tempo de ciclo (segundos)      |
| oee                | REAL    | OEE (%)                        |
