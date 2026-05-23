# skill: producao_diaria_vs_meta
# descricao: Gráfico de produção diária vs meta — barras de produção, linha de meta, filtros por turno e linha de produção.
# palavras-chave: produção diária, meta, produzido, target, barras, histórico, phonex, turno, linha

---

## Endpoint

`GET /production/historical`

---

## Parâmetros da API

| Parâmetro | Tipo    | Valores aceitos | Descrição                                       |
|-----------|---------|------------------|-------------------------------------------------|
| from      | string  | YYYY-MM-DD       | Data inicial do período                         |
| to        | string  | YYYY-MM-DD       | Data final do período                           |
| shift     | string  | `A`, `B`, `C`    | Turno — omitir retorna agregado dos três turnos |
| line      | integer | `1`, `2`, `3`, `4` | Linha de produção — omitir retorna todas      |

**Chave sugerida para chamar_api:** `producao`

---

## Linhas disponíveis

| Linha   | Modelo atual (pode mudar) |
|---------|---------------------------|
| `line=1` | PhoneX Pro               |
| `line=2` | PhoneX Lite              |
| `line=3` | PhoneX Ultra             |
| `line=4` | PhoneX Mini              |

> O modelo associado a cada linha pode mudar. Use `GET /lines` para descobrir o modelo vigente. Sempre filtre por `line=<número>`, nunca por nome de modelo.

---

## Colunas relevantes

| Coluna   | Tipo  | Descrição                                           |
|----------|-------|-----------------------------------------------------|
| date     | str   | Data YYYY-MM-DD — eixo X                            |
| produced | int   | Unidades produzidas no dia                          |
| target   | int   | Meta diária de unidades                             |
| defects  | int   | Defeitos no dia (útil para contexto)                |

---

## Gráfico padrão — barras produção + linha de meta

Use quando o usuário pedir produção diária, produção vs meta, desempenho diário, ou histórico de produção.

```python
x = pd.to_datetime(producao['date']).dt.strftime('%d/%m')
n = len(x)

fig, ax = plt.subplots(figsize=(10, 4))

# Barras coloridas: verde se atingiu a meta, azul se não atingiu
cores = ['#34d399' if p >= t else '#60a5fa'
         for p, t in zip(producao['produced'], producao['target'])]
ax.bar(range(n), producao['produced'], color=cores, width=0.7, alpha=0.9, label='Produzido')

# Linha de meta
ax.plot(range(n), producao['target'], color='#475569', linestyle='--',
        linewidth=1.5, label='Meta')

# Média do período
media = producao['produced'].mean()
ax.axhline(media, color='#94a3b8', linestyle=':', linewidth=1,
           label=f'Média {media:,.0f} un.')

step = max(1, n // 10)
ax.set_xticks(range(0, n, step))
ax.set_xticklabels(x[::step], rotation=45, ha='right', fontsize=8)
ax.set_title('Produção Diária vs Meta', color='#1e293b', fontsize=12)
ax.set_ylabel('Unidades', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

> Barras **verdes** = dia que atingiu ou superou a meta. Barras **azuis** = dia abaixo da meta.

---

## Variante — comparativo entre linhas

Use quando o usuário quiser comparar a produção de duas ou mais linhas lado a lado. Requer uma chamada por linha.

```python
# Pressupõe linha1, linha2, linha3, linha4 carregados via chamar_api (line=1..4)
# Use apenas as linhas solicitadas pelo usuário
linhas = [
    (linha1, 'Linha 1', '#60a5fa'),
    (linha2, 'Linha 2', '#34d399'),
    (linha3, 'Linha 3', '#a78bfa'),
    (linha4, 'Linha 4', '#fbbf24'),
]

x_ref = pd.to_datetime(linha1['date']).dt.strftime('%d/%m')
n = len(x_ref)
width = 0.2
x = range(n)

fig, ax = plt.subplots(figsize=(11, 4))
for i, (df, nome, cor) in enumerate(linhas):
    offset = (i - len(linhas) / 2 + 0.5) * width
    ax.bar([xi + offset for xi in x], df['produced'], width=width,
           color=cor, label=nome, alpha=0.9)

step = max(1, n // 10)
ax.set_xticks(list(x)[::step])
ax.set_xticklabels(x_ref[::step], rotation=45, ha='right', fontsize=8)
ax.set_title('Produção Diária por Linha', color='#1e293b', fontsize=12)
ax.set_ylabel('Unidades', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variantes comuns

| Pedido do usuário                              | Adaptação                                                               |
|------------------------------------------------|-------------------------------------------------------------------------|
| "produção da linha 1" / "produção do PhoneX Pro" | Passe `line=1` nos params (consulte `/lines` para confirmar o modelo) |
| "quantos dias abaixo da meta"                  | `(producao['produced'] < producao['target']).sum()`                     |
| "melhor e pior dia"                            | `producao.loc[producao['produced'].idxmax()]` e `idxmin()`              |
| "comparar duas linhas"                         | Duas chamadas API com `line` diferente + variante comparativo           |
| "produção do turno A da linha 3"               | `shift=A` + `line=3` na mesma chamada                                   |
| "% de dias que bateu a meta"                   | `(producao['produced'] >= producao['target']).mean() * 100`             |

---

## Cores e tema

| Elemento              | Cor              |
|-----------------------|------------------|
| Dia que atingiu meta  | `#34d399`        |
| Dia abaixo da meta    | `#60a5fa`        |
| Meta                  | `#475569` dashed |
| Média do período      | `#94a3b8` dotted |
| Linha 1               | `#60a5fa`        |
| Linha 2               | `#34d399`        |
| Linha 3               | `#a78bfa`        |
| Linha 4               | `#fbbf24`        |
| Fundo figure          | `white`        |
| Fundo eixos           | `white`        |
| Texto/ticks           | `#334155`        |
| Título                | `#1e293b`        |
