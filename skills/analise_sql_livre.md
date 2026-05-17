# skill: analise_sql_livre
# descricao: Análise ad-hoc via SQL direto no banco — use quando nenhuma outra skill cobrir o pedido. Acesso completo a todas as tabelas.
# palavras-chave: sql, consulta, ad-hoc, livre, cruzamento, join, correlação, ranking, personalizado, customizado, combinação de tabelas

---

## Quando usar esta skill

Use esta skill **somente quando** o pedido do usuário não puder ser atendido por nenhuma outra skill disponível (por exemplo, cruzamentos de tabelas, análises que mesclam produção + defeitos + métricas em uma única query, rankings, ou qualquer análise que exija SQL customizado).

---

## Fluxo obrigatório

```
1. read_skill('analise_sql_livre.md')          ← você já está aqui
2. executar_sql(query=<SELECT...>, chave=<nome>) ← injeta DataFrame no ambiente
3. analisar_dataframe(script)                  ← processa e gera resultado
```

**NÃO chame `calcular_periodo` nem `chamar_api` neste fluxo.** As datas devem ser calculadas diretamente no SQL usando a data de hoje informada no prompt.

---

## Regras de segurança

- Apenas `SELECT` é permitido. Qualquer outra instrução (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, etc.) será rejeitada automaticamente com erro.
- Não use `SELECT *` — liste as colunas que precisa para manter o DataFrame enxuto.

---

## Schema completo do banco

### Tabela `production`
Uma linha por combinação (date, shift, line, model) — dados granulares de produção.

| Coluna   | Tipo    | Descrição                                              |
|----------|---------|--------------------------------------------------------|
| id       | INTEGER | PK autoincrement                                       |
| date     | TEXT    | Data ISO `YYYY-MM-DD`                                  |
| shift    | TEXT    | Turno: `A`, `B` ou `C`                                 |
| line     | INTEGER | Linha: `1`, `2`, `3` ou `4`                            |
| model    | TEXT    | Modelo: `PhoneX Pro`, `PhoneX Lite`, `PhoneX Ultra`, `PhoneX Mini` |
| produced | INTEGER | Unidades produzidas                                    |
| target   | INTEGER | Meta de produção                                       |

Índices: `date`, `shift`, `line`, `model`

---

### Tabela `defects`
Uma linha por combinação (date, shift, line, category) — defeitos granulares.

| Coluna   | Tipo    | Descrição                                                                                     |
|----------|---------|-----------------------------------------------------------------------------------------------|
| id       | INTEGER | PK autoincrement                                                                              |
| date     | TEXT    | Data ISO `YYYY-MM-DD`                                                                         |
| shift    | TEXT    | Turno: `A`, `B` ou `C`                                                                        |
| line     | INTEGER | Linha: `1`, `2`, `3` ou `4`                                                                   |
| category | TEXT    | Categoria: `Tela (display)`, `Câmera`, `Bateria`, `Placa-mãe`, `Chassi / Carcaça`, `Conector USB`, `Outros` |
| count    | INTEGER | Quantidade de defeitos                                                                        |

Índices: `date`, `shift`, `line`, `category`

---

### Tabela `metrics`
Uma linha por dia — métricas consolidadas por turno (FPY, OEE, eficiência).

| Coluna              | Tipo  | Descrição                                      |
|---------------------|-------|------------------------------------------------|
| id                  | INTEGER | PK autoincrement                             |
| date                | TEXT  | Data ISO `YYYY-MM-DD` (UNIQUE)                 |
| label               | TEXT  | Dia da semana abreviado (`Seg`, `Ter`, …)      |
| fpy_a               | REAL  | First Pass Yield turno A (%)                   |
| oee_a               | REAL  | OEE turno A (%)                                |
| fpy_b               | REAL  | First Pass Yield turno B (%)                   |
| oee_b               | REAL  | OEE turno B (%)                                |
| fpy_c               | REAL  | First Pass Yield turno C (%)                   |
| oee_c               | REAL  | OEE turno C (%)                                |
| availability        | REAL  | Disponibilidade OEE (%)                        |
| performance         | REAL  | Performance OEE (%)                            |
| shift_a_efficiency  | INTEGER | Eficiência turno A (%)                       |
| shift_b_efficiency  | INTEGER | Eficiência turno B (%)                       |
| shift_c_efficiency  | INTEGER | Eficiência turno C (%)                       |

---

### Tabela `hourly_production`
Uma linha por (date, shift, line, model, hour) — produção hora a hora.

| Coluna   | Tipo    | Descrição                                              |
|----------|---------|--------------------------------------------------------|
| id       | INTEGER | PK autoincrement                                       |
| date     | TEXT    | Data ISO `YYYY-MM-DD`                                  |
| shift    | TEXT    | Turno: `A`, `B` ou `C`                                 |
| line     | INTEGER | Linha: `1`, `2`, `3` ou `4`                            |
| model    | TEXT    | Modelo do produto                                      |
| hour     | TEXT    | Hora no formato `06h`, `07h`, …, `23h`, `00h`, …`05h` |
| produced | INTEGER | Unidades produzidas naquela hora                       |
| target   | INTEGER | Meta horária                                           |
| defects  | INTEGER | Defeitos naquela hora                                  |

Índices: `date`, `shift`, `model`

---

### Tabela `lines_status`
Snapshot estático do estado atual de cada linha (não tem dados históricos).

| Coluna    | Tipo    | Descrição                                      |
|-----------|---------|------------------------------------------------|
| id        | INTEGER | Linha (1–4)                                    |
| name      | TEXT    | Nome (`Linha 1`, …, `Linha 4`)                 |
| model     | TEXT    | Modelo sendo produzido                         |
| status    | TEXT    | `running`, `stopped`, `maintenance`            |
| produced  | INTEGER | Produção acumulada do dia                      |
| target    | INTEGER | Meta diária                                    |
| fpy       | REAL    | FPY atual (%)                                  |
| speed_pct | INTEGER | Velocidade em % da capacidade                  |
| operator  | TEXT    | Operador responsável                           |

---

### Tabela `alerts`
Alertas registrados com severidade e linha associada.

| Coluna       | Tipo    | Descrição                                      |
|--------------|---------|------------------------------------------------|
| id           | INTEGER | PK autoincrement                               |
| datetime     | TEXT    | Datetime ISO `YYYY-MM-DDTHH:MM:SS`             |
| severity     | TEXT    | `critical`, `warning`, `info`                  |
| line         | INTEGER | Linha relacionada (1–4)                        |
| message      | TEXT    | Descrição do alerta                            |
| acknowledged | INTEGER | `0` = não reconhecido, `1` = reconhecido       |

---

### Tabela `kpis`
Snapshot de KPIs por turno (uma linha por turno A/B/C).

| Coluna             | Tipo    | Descrição                             |
|--------------------|---------|---------------------------------------|
| shift              | TEXT    | PK: `A`, `B` ou `C`                   |
| total_produced     | INTEGER | Total produzido no turno              |
| daily_target       | INTEGER | Meta do turno                         |
| first_pass_yield   | REAL    | FPY (%)                               |
| defect_rate        | REAL    | Taxa de defeito (%)                   |
| downtime_minutes   | INTEGER | Tempo de parada (minutos)             |
| efficiency         | REAL    | Eficiência (%)                        |
| scrapped           | INTEGER | Unidades descartadas                  |
| reworked           | INTEGER | Unidades retrabalhadas                |
| cycle_time_seconds | REAL    | Tempo de ciclo (segundos)             |
| oee                | REAL    | OEE (%)                               |

---

## Exemplos de queries úteis

### Cruzar produção com defeitos por linha no último mês
```sql
SELECT
    p.date,
    p.line,
    SUM(p.produced) AS produced,
    SUM(p.target)   AS target,
    COALESCE(SUM(d.count), 0) AS total_defects,
    ROUND(100.0 * COALESCE(SUM(d.count), 0) / NULLIF(SUM(p.produced), 0), 2) AS defect_rate_pct
FROM production p
LEFT JOIN defects d ON p.date = d.date AND p.shift = d.shift AND p.line = d.line
WHERE p.date >= date('now', '-30 days')
GROUP BY p.date, p.line
ORDER BY p.date, p.line
```

### Ranking de categorias de defeito por turno
```sql
SELECT
    d.shift,
    d.category,
    SUM(d.count) AS total,
    ROUND(100.0 * SUM(d.count) / SUM(SUM(d.count)) OVER (PARTITION BY d.shift), 1) AS pct
FROM defects d
WHERE d.date >= date('now', '-30 days')
GROUP BY d.shift, d.category
ORDER BY d.shift, total DESC
```

### Correlação produção × OEE por dia
```sql
SELECT
    p.date,
    SUM(p.produced) AS produced,
    m.oee_a,
    m.oee_b,
    m.oee_c,
    (m.oee_a + m.oee_b + m.oee_c) / 3.0 AS oee_avg
FROM production p
JOIN metrics m ON p.date = m.date
WHERE p.date >= date('now', '-30 days')
GROUP BY p.date
ORDER BY p.date
```

### Produção por hora agregada (perfil intradiário)
```sql
SELECT
    h.hour,
    h.shift,
    SUM(h.produced) AS produced,
    SUM(h.defects)  AS defects
FROM hourly_production h
WHERE h.date >= date('now', '-7 days')
GROUP BY h.shift, h.hour
ORDER BY h.shift, h.hour
```

---

## Ambiente de execução

O script em `analisar_dataframe` tem acesso às seguintes bibliotecas pré-importadas:

| Variável | Biblioteca        | Uso principal                    |
|----------|-------------------|----------------------------------|
| `pd`     | pandas            | DataFrames, filtros, agregações  |
| `np`     | numpy             | Operações numéricas              |
| `plt`    | matplotlib.pyplot | Geração de gráficos              |
| `stats`  | scipy.stats       | Testes estatísticos              |

A variável definida em `chave` de `executar_sql` fica disponível como DataFrame no ambiente.
Atribua à variável `result` o que deve ser exibido (figura, DataFrame ou string).

---

## Geração de gráficos

Use `facecolor='white'` no figure e eixos para manter o tema escuro.
Cores recomendadas: produzido `#60a5fa`, defeitos `#f87171`, meta `#475569` (dashed),
FPY/verde `#34d399`, OEE/roxo `#a78bfa`, amarelo `#fbbf24`.
Sempre use `pd.to_datetime(df['date']).dt.strftime('%d/%m')` no eixo X quando houver coluna `date`.
Atribua `result = fig` para exibir o gráfico.
