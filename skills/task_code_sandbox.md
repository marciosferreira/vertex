# skill: task_code_sandbox
# descricao: Regras e template obrigatórios para escrever task_code — namespace do sandbox, variáveis pré-injetadas, proibições e exemplos
# palavras-chave: task_code, sandbox, run, imports, namespace, ctx, pd, plt, np

---

## Regra principal

**NUNCA use `import` dentro de `run()` nem fora dela.**
Todas as bibliotecas já estão no namespace — qualquer `import` causa erro imediato.

---

## Variáveis pré-injetadas no namespace

| Variável / Símbolo                                    | O que é                                                                            |
|-------------------------------------------------------|------------------------------------------------------------------------------------|
| `pd`                                                  | pandas                                                                             |
| `np`                                                  | numpy                                                                              |
| `plt`                                                 | matplotlib.pyplot                                                                  |
| `mticker`                                             | matplotlib.ticker                                                                  |
| `mdates`                                              | matplotlib.dates — use `mdates.DateFormatter('%d/%m')` para formatar eixo de datas |
| `openpyxl`                                            | openpyxl (módulo)                                                                  |
| `Font`, `PatternFill`, `Alignment`, `Border`, `Side`  | openpyxl.styles                                                                    |
| `get_column_letter`                                   | openpyxl.utils                                                                     |
| `date`, `datetime`, `timedelta`                       | do módulo datetime                                                                 |
| `time`, `math`, `json`, `re`                          | stdlib leve (pré-injetados — não precisa importar)                                 |
| `Counter`, `defaultdict`                              | collections (pré-injetados)                                                        |
| `from_date`, `to_date`                                | objetos `date` — suportam `.strftime()`, `.year` etc. `str(from_date)` → YYYY-MM-DD |
| `ctx`                                                 | TaskContext — métodos abaixo                                                       |

### Métodos do ctx

| Chamada                                       | Retorna                                   |
|-----------------------------------------------|-------------------------------------------|
| `ctx.api('/endpoint?from=X&to=Y')`            | list de dicts com os dados da API         |

> **ATENÇÃO:** `ctx.api()` recebe **apenas o path** começando com `/` — NUNCA a URL completa.
> `ctx.api('/production/historical?...')` ✅ — `ctx.api('http://localhost:8000/...')` ❌
| `ctx.today()`                                 | string YYYY-MM-DD com a data atual        |
| `ctx.date_range(days=N)`                      | `(from_date, to_date)` dos últimos N dias |
| `ctx.save_chart(fig)`                         | token `[chart:uuid]`                      |
| `ctx.generate_excel(df, 'Nome')`              | token `[excel:uuid]`                      |
| `ctx.generate_pdf('Título', 'conteudo')`      | token `[pdf:uuid]`                        |
| `ctx.notify(msg, value=None, threshold=None)` | dispara notificação no dashboard          |

---

## Templates canônicos

### Relatório (PDF com gráfico embutido) — padrão para "relatório", "report", "resumo"

```python
def run(from_date, to_date, ctx):
    # SEM imports — pd, np, plt, ctx etc já estão disponíveis
    dados = ctx.api(f'/endpoint?from={from_date}&to={to_date}')
    df = pd.DataFrame(dados)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df['date'], df['valor'])
    plt.tight_layout()
    chart = ctx.save_chart(fig)

    # NÃO use df.to_markdown() no conteúdo do PDF — causa erro de layout.
    # Inclua apenas o token do gráfico e bullet points com valores agregados.
    media = df['valor'].mean()
    conteudo = (
        f"## Visão Geral\n\n"
        f"{chart}\n\n"
        f"- Período: {from_date.strftime('%d/%m/%Y')} a {to_date.strftime('%d/%m/%Y')}\n"
        f"- Média: {media:.1f}\n"
        f"- Máximo: {df['valor'].max():.1f}\n"
        f"- Mínimo: {df['valor'].min():.1f}\n"
    )
    return ctx.generate_pdf('Título do Relatório', conteudo)
```

### Apenas gráfico — para "gráfico", "chart", "visualização"

```python
def run(from_date, to_date, ctx):
    dados = ctx.api(f'/endpoint?from={from_date}&to={to_date}')
    df = pd.DataFrame(dados)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df['date'], df['valor'])
    plt.tight_layout()
    return ctx.save_chart(fig)
```

### Planilha Excel — SOMENTE quando o usuário pedir "planilha", "Excel" ou ".xlsx"

```python
def run(from_date, to_date, ctx):
    dados = ctx.api(f'/endpoint?from={from_date}&to={to_date}')
    df = pd.DataFrame(dados)
    return ctx.generate_excel(df, 'nome_arquivo')
```

---

## Erros comuns — NÃO faça isso

```python
# ERRADO — ctx.api() não aceita URL completa (diferente de chamar_api do chat)
dados = ctx.api('http://localhost:8000/production/historical?from=...')  # ERRADO

# CERTO — apenas o path, começando com /
dados = ctx.api(f'/production/historical?from={from_date}&to={to_date}')  # CERTO
```

```python
# ERRADO — causa ImportError no sandbox (pd, plt, np já estão disponíveis)
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime, date, timedelta
import numpy as np

def run(from_date, to_date, ctx):
    ...
```

```python
# ERRADO — import dentro do run() também causa ImportError
def run(from_date, to_date, ctx):
    import numpy as np   # proibido — use np diretamente
    ...
```

```python
# ERRADO — nunca retorne a figura diretamente
def run(from_date, to_date, ctx):
    fig, ax = plt.subplots()
    ...
    return fig   # use ctx.save_chart(fig)
```

```python
# ERRADO — ha= não existe em tick_params, causa TypeError
ax.tick_params(axis='x', rotation=45, ha='right')  # ERRADO

# CERTO — para rotacionar rótulos do eixo X com alinhamento:
plt.setp(ax.get_xticklabels(), rotation=45, ha='right')  # CERTO
```

```python
# CERTO — pd.to_datetime().dt.strftime() funciona normalmente
x_labels = pd.to_datetime(df['date']).dt.strftime('%d/%m')

# CERTO — from_date é objeto date, .strftime() funciona
titulo = f"Relatório {from_date.strftime('%d/%m/%Y')} a {to_date.strftime('%d/%m/%Y')}"

# CERTO — str(from_date) retorna YYYY-MM-DD para uso em URLs de API
dados = ctx.api(f'/production/historical?from={from_date}&to={to_date}')
```

---

## Monitores (every\_Xm / every\_Xh)

Monitores DEVEM sempre retornar uma string com o valor atual, mesmo quando o threshold não for atingido.

```python
def run(from_date, to_date, ctx):
    hoje = ctx.today()
    dados = ctx.api(f'/production/oee?from={hoje}&to={hoje}')
    df = pd.DataFrame(dados)
    oee = df['oee'].mean()
    if oee < 80:
        ctx.notify(f'OEE {oee:.1f}% abaixo de 80%', value=oee, threshold=80)
    return f'OEE: {oee:.2f}% (ref: 80%)'
```
