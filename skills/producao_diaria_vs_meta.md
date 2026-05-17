# skill: producao_diaria_vs_meta
# descricao: Gráfico de produção diária vs meta — barras de produção, linha de meta, filtros por turno, linha e modelo de aparelho.
# palavras-chave: produção diária, meta, produzido, target, barras, histórico, modelo, phonex, turno, linha

---

## Endpoint

`GET http://localhost:8000/production/historical`

---

## Parâmetros da API

| Parâmetro | Tipo   | Valores aceitos                                              | Descrição                                       |
|-----------|--------|--------------------------------------------------------------|-------------------------------------------------|
| from      | string | YYYY-MM-DD                                                   | Data inicial do período                         |
| to        | string | YYYY-MM-DD                                                   | Data final do período                           |
| shift     | string | `A`, `B`, `C`                                                | Turno — omitir retorna agregado dos três turnos |
| model     | string | `PhoneX Pro`, `PhoneX Lite`, `PhoneX Ultra`, `PhoneX Mini`   | Modelo do aparelho — omitir retorna todos       |

**Chave sugerida para chamar_api:** `producao`

---

## Modelos disponíveis

| Modelo        | Linha de produção |
|---------------|-------------------|
| PhoneX Pro    | Linha 1           |
| PhoneX Lite   | Linha 2           |
| PhoneX Ultra  | Linha 3           |
| PhoneX Mini   | Linha 4           |

> Cada linha produz exclusivamente seu modelo. Filtrar por `model` é equivalente a filtrar pela linha correspondente, mas com semântica mais clara para o usuário.

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

## Variante — comparativo entre modelos

Use quando o usuário quiser comparar a produção de dois ou mais modelos lado a lado. Requer uma chamada por modelo.

```python
# Pressupõe prod_pro, prod_lite, prod_ultra, prod_mini carregados via chamar_api
modelos = [
    (prod_pro,   'PhoneX Pro',   '#60a5fa'),
    (prod_lite,  'PhoneX Lite',  '#34d399'),
    (prod_ultra, 'PhoneX Ultra', '#a78bfa'),
    (prod_mini,  'PhoneX Mini',  '#fbbf24'),
]
# Use apenas os modelos solicitados pelo usuário

x_ref = pd.to_datetime(prod_pro['date']).dt.strftime('%d/%m')
n = len(x_ref)
width = 0.2
x = range(n)

fig, ax = plt.subplots(figsize=(11, 4))
for i, (df, nome, cor) in enumerate(modelos):
    offset = (i - len(modelos) / 2 + 0.5) * width
    ax.bar([xi + offset for xi in x], df['produced'], width=width,
           color=cor, label=nome, alpha=0.9)

step = max(1, n // 10)
ax.set_xticks(list(x)[::step])
ax.set_xticklabels(x_ref[::step], rotation=45, ha='right', fontsize=8)
ax.set_title('Produção Diária por Modelo', color='#1e293b', fontsize=12)
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
| "produção do PhoneX Pro"                       | Passe `model=PhoneX Pro` nos params                                     |
| "produção da linha 1"                          | Equivalente a `model=PhoneX Pro` (Linha 1 = PhoneX Pro)                 |
| "quantos dias abaixo da meta"                  | `(producao['produced'] < producao['target']).sum()`                     |
| "melhor e pior dia"                            | `producao.loc[producao['produced'].idxmax()]` e `idxmin()`              |
| "comparar dois modelos"                        | Duas chamadas API com `model` diferente + variante comparativo          |
| "produção do turno A do PhoneX Ultra"          | `shift=A` + `model=PhoneX Ultra` na mesma chamada                      |
| "% de dias que bateu a meta"                   | `(producao['produced'] >= producao['target']).mean() * 100`             |

---

## Cores e tema

| Elemento              | Cor              |
|-----------------------|------------------|
| Dia que atingiu meta  | `#34d399`        |
| Dia abaixo da meta    | `#60a5fa`        |
| Meta                  | `#475569` dashed |
| Média do período      | `#94a3b8` dotted |
| PhoneX Pro            | `#60a5fa`        |
| PhoneX Lite           | `#34d399`        |
| PhoneX Ultra          | `#a78bfa`        |
| PhoneX Mini           | `#fbbf24`        |
| Fundo figure          | `white`        |
| Fundo eixos           | `white`        |
| Texto/ticks           | `#334155`        |
| Título                | `#1e293b`        |
