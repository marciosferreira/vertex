# skill: tendencia_defeitos
# descricao: Gráfico de tendência de defeitos ao longo do tempo — linha de defeitos diários com regressão linear, média móvel, alertas de piora e projeção futura.
# palavras-chave: tendência, defeitos, regressão, média móvel, piora, melhora, projeção, defect trend, qualidade, evolução

---

## Endpoint

`GET /production/historical`

Os defeitos totais já vêm agregados por dia neste endpoint. Para série de uma categoria específica use `/defects?category=<nome>` (ver skill [[defeitos_por_categoria]]).

---

## Parâmetros da API

| Parâmetro | Tipo   | Valores aceitos | Descrição                                       |
|-----------|--------|-----------------|-------------------------------------------------|
| from      | string | YYYY-MM-DD      | Data inicial do período                         |
| to        | string | YYYY-MM-DD      | Data final do período                           |
| shift     | string | `A`, `B`, `C`   | Turno — omitir retorna agregado dos três turnos |
| model     | string | `PhoneX Pro`, `PhoneX Lite`, `PhoneX Ultra`, `PhoneX Mini` | Modelo do aparelho — omitir retorna todos |

**Chave sugerida para chamar_api:** `producao`

---

## Colunas relevantes

| Coluna   | Tipo  | Descrição                                    |
|----------|-------|----------------------------------------------|
| date     | str   | Data YYYY-MM-DD — eixo X                     |
| defects  | int   | Total de defeitos no dia                     |
| produced | int   | Total produzido — usado para taxa de defeitos|
| fpy      | float | First Pass Yield — inverso da taxa de defeito|

---

## Gráfico padrão — tendência com regressão linear

Use quando o usuário pedir tendência de defeitos, se defeitos estão aumentando/diminuindo, ou evolução da qualidade.

```python
x_labels = pd.to_datetime(producao['date']).dt.strftime('%d/%m')
n  = len(x_labels)
x  = np.arange(n)
y  = producao['defects'].values.astype(float)

# Regressão linear
coef  = np.polyfit(x, y, 1)
trend = np.poly1d(coef)
y_fit = trend(x)

# Média móvel 7 dias
mm7 = pd.Series(y).rolling(7, min_periods=1).mean().values

# Direção da tendência
sentido   = 'alta ▲' if coef[0] > 0 else 'queda ▼'
variacao  = abs(coef[0]) * (n - 1)
cor_trend = '#f87171' if coef[0] > 0 else '#34d399'

fig, ax = plt.subplots(figsize=(10, 4))

# Barras diárias
ax.bar(x, y, color='#f87171', alpha=0.35, width=0.8, label='Defeitos/dia')

# Média móvel
ax.plot(x, mm7, color='#fbbf24', linewidth=1.8, label='Média móvel 7d')

# Linha de tendência
ax.plot(x, y_fit, color=cor_trend, linewidth=2, linestyle='--',
        label=f'Tendência ({sentido} {variacao:.0f} un. no período)')

# Média geral
media = y.mean()
ax.axhline(media, color='#94a3b8', linestyle=':', linewidth=1, label=f'Média {media:.1f}')

step = max(1, n // 10)
ax.set_xticks(x[::step])
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)
ax.set_title('Tendência de Defeitos', color='#1e293b', fontsize=12)
ax.set_ylabel('Defeitos / dia', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

> Inclua sempre na resposta a interpretação: se `coef[0] > 0`, defeitos estão aumentando; se `< 0`, estão caindo. Mencione a variação total estimada pela regressão.

---

## Variante — taxa de defeitos (% sobre produção)

Use quando o usuário quiser proporção em vez de volume absoluto, ou quando a produção variou muito no período.

```python
taxa = (producao['defects'] / producao['produced'] * 100).values
coef = np.polyfit(np.arange(len(taxa)), taxa, 1)
trend_taxa = np.poly1d(coef)(np.arange(len(taxa)))

fig, ax = plt.subplots(figsize=(10, 4))
ax.fill_between(range(len(taxa)), taxa, alpha=0.2, color='#f87171')
ax.plot(range(len(taxa)), taxa,       color='#f87171', linewidth=1.8, label='Taxa defeitos (%)')
ax.plot(range(len(taxa)), trend_taxa, color='#fbbf24', linewidth=2,
        linestyle='--', label='Tendência')

x_labels = pd.to_datetime(producao['date']).dt.strftime('%d/%m')
step = max(1, len(taxa) // 10)
ax.set_xticks(range(0, len(taxa), step))
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)
ax.set_title('Taxa de Defeitos — Tendência (%)', color='#1e293b', fontsize=12)
ax.set_ylabel('Defeitos / Produção (%)', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — projeção dos próximos N dias

Use quando o usuário pedir previsão, projeção ou forecast de defeitos.

```python
n_proj = 7  # ajuste conforme solicitado pelo usuário

x_hist = np.arange(n)
coef   = np.polyfit(x_hist, y, 1)
trend  = np.poly1d(coef)

x_proj  = np.arange(n, n + n_proj)
y_proj  = trend(x_proj).clip(min=0)

# Labels fictícios para o eixo X da projeção
last_date = pd.to_datetime(producao['date'].iloc[-1])
proj_dates = pd.date_range(last_date + pd.Timedelta(days=1), periods=n_proj)
proj_labels = proj_dates.strftime('%d/%m').tolist()

x_all    = list(range(n + n_proj))
y_all    = list(y) + list(y_proj)
labels_all = list(x_labels) + proj_labels
cor_all  = ['#f87171'] * n + ['#fb923c'] * n_proj

fig, ax = plt.subplots(figsize=(11, 4))
ax.bar(x_all, y_all, color=cor_all, alpha=0.75, width=0.8)
ax.axvline(n - 0.5, color='#475569', linestyle='--', linewidth=1.2, label='Início projeção')
ax.plot(x_hist, trend(x_hist), color='#94a3b8', linewidth=1.5, linestyle=':')
ax.plot(range(n - 1, n + n_proj), [trend(n - 1)] + list(y_proj),
        color='#fb923c', linewidth=2, linestyle='--', label=f'Projeção {n_proj}d')

step = max(1, (n + n_proj) // 12)
ax.set_xticks(x_all[::step])
ax.set_xticklabels(labels_all[::step], rotation=45, ha='right', fontsize=8)
ax.set_title(f'Defeitos — Histórico + Projeção {n_proj} dias', color='#1e293b', fontsize=12)
ax.set_ylabel('Defeitos / dia', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Análise estatística de tendência

Sempre que plotar tendência, calcule e informe na resposta:

```python
# Significância da tendência (se a inclinação é estatisticamente diferente de zero)
from scipy.stats import linregress
slope, intercept, r_value, p_value, std_err = stats.linregress(np.arange(n), y)

# Interprete:
# p_value < 0.05 → tendência significativa
# r_value**2     → força da tendência (R²)
# slope > 0      → defeitos aumentando X unidades/dia em média
```

Inclua na resposta: direção, p-value e R². Exemplo: *"Tendência de alta significativa (p=0.02, R²=0.41): defeitos aumentam ~2,3 unidades/dia."*

---

## Variantes comuns

| Pedido do usuário                            | Adaptação                                                         |
|----------------------------------------------|-------------------------------------------------------------------|
| "defeitos estão piorando?"                   | Gráfico padrão + análise estatística                              |
| "taxa de defeitos"                           | Variante taxa (% sobre produção)                                  |
| "projeção para a próxima semana"             | Variante projeção com `n_proj=7`                                  |
| "tendência de Tela (display)"                | Chamada `/defects?category=Tela (display)` + mesmo gráfico       |
| "média móvel 14 dias"                        | Troque `rolling(7)` por `rolling(14)`                             |
| "comparar tendência entre turnos"            | Três chamadas com `shift`, três linhas de tendência no mesmo eixo |

---

## Cores e tema

| Elemento            | Cor                       |
|---------------------|---------------------------|
| Barras históricas   | `#f87171` + `alpha=0.35`  |
| Barras projeção     | `#fb923c` + `alpha=0.75`  |
| Média móvel 7d      | `#fbbf24`                 |
| Tendência queda     | `#34d399` dashed          |
| Tendência alta      | `#f87171` dashed          |
| Projeção            | `#fb923c` dashed          |
| Média geral         | `#94a3b8` dotted          |
| Marco início proj.  | `#475569` dashed          |
| Fundo figure        | `white`                 |
| Fundo eixos         | `white`                 |
| Texto/ticks         | `#334155`                 |
| Título              | `#1e293b`                 |
