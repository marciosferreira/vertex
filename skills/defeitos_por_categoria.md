# skill: defeitos_por_categoria
# descricao: Gráfico de defeitos por categoria — Pareto, pizza, série temporal de uma categoria, comparativo por turno ou linha.
# palavras-chave: defeitos, categoria, pareto, tela, câmera, bateria, placa-mãe, chassi, conector, qualidade, defect, category

---

## Endpoint

`GET /defects`

Comportamento **muda** conforme o parâmetro `category`:

| Sem `category`         | Com `category`                    |
|------------------------|-----------------------------------|
| Agrega por categoria → retorna ranking com `count` e `percentage` | Série temporal → um ponto por dia |

---

## Parâmetros da API

| Parâmetro | Tipo   | Obrigatório | Valores aceitos                        | Descrição                                         |
|-----------|--------|-------------|----------------------------------------|---------------------------------------------------|
| from      | string | não         | YYYY-MM-DD                             | Data inicial                                      |
| to        | string | não         | YYYY-MM-DD                             | Data final                                        |
| shift     | string | não         | `A`, `B`, `C`                          | Filtra por turno                                  |
| line      | integer | não        | `1`, `2`, `3`, `4`                                         | Filtra por linha de produção                                        |
| category  | string | não         | nome exato (ver tabela abaixo)         | Ativa modo série temporal para uma categoria      |

### Categorias existentes

| Categoria             | Descrição                  |
|-----------------------|----------------------------|
| `Tela (display)`      | Defeitos de tela           |
| `Câmera`              | Defeitos de câmera         |
| `Bateria`             | Defeitos de bateria        |
| `Placa-mãe`           | Defeitos de placa-mãe      |
| `Chassi / Carcaça`    | Defeitos estruturais       |
| `Conector USB`        | Defeitos de conector USB   |
| `Outros`              | Demais defeitos            |

**Chave sugerida para chamar_api:** `defeitos`

---

## Colunas do DataFrame

### Modo agregado (sem `category`)

| Coluna     | Tipo  | Descrição                          |
|------------|-------|------------------------------------|
| category   | str   | Nome da categoria                  |
| count      | int   | Total de defeitos no período       |
| percentage | float | Participação % no total            |

### Modo série temporal (com `category`)

| Coluna | Tipo | Descrição              |
|--------|------|------------------------|
| date   | str  | Data YYYY-MM-DD        |
| count  | int  | Defeitos nessa data    |

---

## Gráfico padrão — Pareto de defeitos

Use quando o usuário pedir defeitos por categoria, ranking, quais categorias causam mais defeitos, ou Pareto de qualidade.

```python
cats  = defeitos['category'].tolist()
cnts  = defeitos['count'].values
pcts  = defeitos['percentage'].values

# Linha de Pareto acumulado
acum  = pcts.cumsum()

cores_bar = ['#f87171','#fbbf24','#60a5fa','#34d399','#a78bfa','#fb923c','#94a3b8']
x = range(len(cats))

fig, ax = plt.subplots(figsize=(10, 4))
bars = ax.bar(x, cnts, color=cores_bar[:len(cats)], width=0.6, alpha=0.9)

# Valores acima de cada barra
for bar, val, pct in zip(bars, cnts, pcts):
    ax.text(bar.get_x() + bar.get_width() / 2, val + cnts.max() * 0.01,
            f'{val}\n({pct:.1f}%)', ha='center', fontsize=8, color='#1e293b')

# Linha de Pareto acumulado em eixo secundário
ax2 = ax.twinx()
ax2.plot(list(x), acum, color='#1e293b', linewidth=1.5,
         marker='D', markersize=4, label='Acumulado (%)')
ax2.axhline(80, color='#475569', linestyle='--', linewidth=1, label='80% (Pareto)')
ax2.set_ylim(0, 115)
ax2.set_ylabel('% Acumulado', color='#94a3b8')
ax2.tick_params(colors='#94a3b8')

ax.set_xticks(list(x))
ax.set_xticklabels(cats, rotation=30, ha='right', fontsize=8)
ax.set_title('Defeitos por Categoria — Pareto', color='#1e293b', fontsize=12)
ax.set_ylabel('Quantidade', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')

lines2, labels2 = ax2.get_legend_handles_labels()
ax2.legend(lines2, labels2, facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — pizza (distribuição proporcional)

Use quando o usuário pedir pizza, proporção ou participação de cada categoria.

```python
cats  = defeitos['category'].tolist()
cnts  = defeitos['count'].values
cores = ['#f87171','#fbbf24','#60a5fa','#34d399','#a78bfa','#fb923c','#94a3b8']

fig, ax = plt.subplots(figsize=(7, 5))
wedges, texts, autotexts = ax.pie(
    cnts, labels=cats, colors=cores[:len(cats)],
    autopct='%1.1f%%', startangle=140,
    wedgeprops=dict(edgecolor='white', linewidth=1.5),
    pctdistance=0.78,
)
for t in texts:
    t.set_color('#94a3b8')
    t.set_fontsize(8)
for at in autotexts:
    at.set_color('white')
    at.set_fontsize(8)
    at.set_fontweight('bold')

ax.set_title('Distribuição de Defeitos por Categoria', color='#1e293b', fontsize=12)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — série temporal de uma categoria

Use quando o usuário quiser ver a evolução de uma categoria específica ao longo do tempo.
Requer segunda chamada API com `category` preenchido.

```python
# Ex: chamar_api com category='Tela (display)', chave='tela'
x_labels = pd.to_datetime(tela['date']).dt.strftime('%d/%m')
n = len(x_labels)
x = range(n)

fig, ax = plt.subplots(figsize=(10, 4))
ax.fill_between(x, tela['count'].values, alpha=0.15, color='#f87171')
ax.plot(x, tela['count'].values, color='#f87171', linewidth=2, marker='o', markersize=3)

media = tela['count'].mean()
ax.axhline(media, color='#94a3b8', linestyle=':', linewidth=1, label=f'Média {media:.1f}')

step = max(1, n // 10)
ax.set_xticks(list(x)[::step])
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)
ax.set_title('Defeitos — Tela (display)', color='#1e293b', fontsize=12)
ax.set_ylabel('Defeitos / dia', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — comparativo por turno

Use quando o usuário quiser ver quais categorias predominam em cada turno. Requer três chamadas API (uma por turno, sem `category`).

```python
# Pressupõe def_a, def_b, def_c — DataFrames com category/count por turno
cats = def_a['category'].tolist()
x = range(len(cats))
width = 0.25

fig, ax = plt.subplots(figsize=(11, 4))
for i, (df, nome, cor) in enumerate(zip(
    [def_a, def_b, def_c], ['Turno A','Turno B','Turno C'],
    ['#60a5fa','#34d399','#f87171']
)):
    vals = df.set_index('category').reindex(cats)['count'].fillna(0).values
    offset = (i - 1) * width
    ax.bar([xi + offset for xi in x], vals, width=width, color=cor, label=nome, alpha=0.9)

ax.set_xticks(list(x))
ax.set_xticklabels(cats, rotation=30, ha='right', fontsize=8)
ax.set_title('Defeitos por Categoria — Comparativo por Turno', color='#1e293b', fontsize=12)
ax.set_ylabel('Quantidade', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variantes comuns

| Pedido do usuário                              | Adaptação                                                              |
|------------------------------------------------|------------------------------------------------------------------------|
| "Pareto de defeitos"                           | Gráfico padrão acima                                                   |
| "pizza de defeitos"                            | Variante pizza                                                         |
| "evolução de Tela ao longo do tempo"           | Segunda chamada com `category='Tela (display)'` + variante série       |
| "defeitos por turno"                           | Variante comparativo por turno (3 chamadas)                            |
| "defeitos da linha 2"                          | Adicione `line=2` nos params da chamada                                |
| "categorias que causam 80% dos defeitos"       | Filtre `defeitos[defeitos['percentage'].cumsum() <= 80]`               |

---

## Cores e tema

| Elemento          | Cor       |
|-------------------|-----------|
| Tela (display)    | `#f87171` |
| Câmera            | `#fbbf24` |
| Bateria           | `#60a5fa` |
| Placa-mãe         | `#34d399` |
| Chassi / Carcaça  | `#a78bfa` |
| Conector USB      | `#fb923c` |
| Outros            | `#94a3b8` |
| Linha Pareto      | `#1e293b` |
| Marco 80%         | `#475569` dashed |
| Fundo figure      | `white` |
| Fundo eixos       | `white` |
| Texto/ticks       | `#334155` |
| Título            | `#1e293b` |
