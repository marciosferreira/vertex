# skill: producao_por_linha
# descricao: Gráfico comparativo de produção por linha (line1–line4) — barras agrupadas ou empilhadas por dia, com totais e destaque da linha líder.
# palavras-chave: linha, line1, line2, line3, line4, comparativo, produção por linha, barras agrupadas, barras empilhadas

---

## Endpoint

`GET /production/historical`

---

## Parâmetros da API

| Parâmetro | Tipo   | Valores aceitos | Descrição                                       |
|-----------|--------|-----------------|-------------------------------------------------|
| from      | string | YYYY-MM-DD      | Data inicial do período                         |
| to        | string | YYYY-MM-DD      | Data final do período                           |
| shift     | string | `A`, `B`, `C`   | Turno — omitir retorna agregado dos três turnos |

**Chave sugerida para chamar_api:** `producao`

---

## Colunas relevantes

| Coluna  | Tipo | Descrição                        |
|---------|------|----------------------------------|
| date    | str  | Data YYYY-MM-DD — eixo X         |
| line1   | int  | Produção da linha 1 no dia       |
| line2   | int  | Produção da linha 2 no dia       |
| line3   | int  | Produção da linha 3 no dia       |
| line4   | int  | Produção da linha 4 no dia       |
| target  | int  | Meta diária total                |

---

## Gráfico padrão — barras agrupadas

Use quando o usuário pedir comparativo entre linhas, produção por linha, ou desempenho de cada linha.

```python
x_labels = pd.to_datetime(producao['date']).dt.strftime('%d/%m')
linhas = ['line1', 'line2', 'line3', 'line4']
nomes  = ['Linha 1', 'Linha 2', 'Linha 3', 'Linha 4']
cores  = ['#60a5fa', '#34d399', '#fbbf24', '#f87171']

n = len(x_labels)
n_linhas = len(linhas)
width = 0.2
x = range(n)

fig, ax = plt.subplots(figsize=(11, 4))

for i, (col, nome, cor) in enumerate(zip(linhas, nomes, cores)):
    offset = (i - n_linhas / 2 + 0.5) * width
    ax.bar([xi + offset for xi in x], producao[col], width=width,
           color=cor, label=nome, alpha=0.9)

# Espaçamento automático do eixo X
step = max(1, n // 10)
ax.set_xticks(list(x)[::step])
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)

ax.set_title('Produção por Linha — Comparativo', color='#1e293b', fontsize=12)
ax.set_ylabel('Unidades produzidas', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — barras empilhadas

Use quando o usuário quiser ver a participação de cada linha no total diário.

```python
x_labels = pd.to_datetime(producao['date']).dt.strftime('%d/%m')
linhas = ['line1', 'line2', 'line3', 'line4']
nomes  = ['Linha 1', 'Linha 2', 'Linha 3', 'Linha 4']
cores  = ['#60a5fa', '#34d399', '#fbbf24', '#f87171']

n = len(x_labels)
x = range(n)
bottom = [0] * n

fig, ax = plt.subplots(figsize=(11, 4))

for col, nome, cor in zip(linhas, nomes, cores):
    vals = producao[col].values
    ax.bar(x, vals, bottom=bottom, color=cor, label=nome, alpha=0.9)
    bottom = [b + v for b, v in zip(bottom, vals)]

# Meta total como linha
ax.plot(x, producao['target'], color='#475569', linestyle='--',
        linewidth=1.4, label='Meta total')

step = max(1, n // 10)
ax.set_xticks(list(x)[::step])
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)

ax.set_title('Produção por Linha — Empilhada', color='#1e293b', fontsize=12)
ax.set_ylabel('Unidades produzidas', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variantes comuns

| Pedido do usuário                            | Adaptação                                                        |
|----------------------------------------------|------------------------------------------------------------------|
| "qual linha produziu mais"                   | Calcule `producao[linhas].sum()` e destaque a maior no título    |
| "produção empilhada"                         | Use a variante empilhada acima                                   |
| "só as linhas 1 e 3"                         | Filtre `linhas` e `nomes` para incluir apenas as solicitadas     |
| Por turno A / B / C                          | Passe `shift` na API antes de chamar `analisar_dataframe`        |
| "percentual de cada linha"                   | Divida cada coluna pela soma do dia: `df[col] / df[linhas].sum(axis=1) * 100` |

---

## Cores e tema

| Elemento     | Cor       |
|--------------|-----------|
| Linha 1      | `#60a5fa` |
| Linha 2      | `#34d399` |
| Linha 3      | `#fbbf24` |
| Linha 4      | `#f87171` |
| Meta         | `#475569` dashed |
| Fundo figure | `white` |
| Fundo eixos  | `white` |
| Texto/ticks  | `#334155` |
| Título       | `#1e293b` |
