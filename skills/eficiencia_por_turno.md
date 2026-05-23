# skill: eficiencia_por_turno
# descricao: Gráfico de eficiência por turno — comparativo A/B/C histórico ou snapshot atual, com barras agrupadas, radar e tendência por turno.
# palavras-chave: eficiência, turno, shift, turno a, turno b, turno c, comparativo turnos, shift_a_efficiency, shift_b_efficiency, shift_c_efficiency, kpi

---

## Endpoints disponíveis

### 1. Histórico diário (série temporal)

`GET /production/historical`

Retorna eficiência de cada turno por dia. **Não passe `shift`** — sem filtro, os três turnos vêm preenchidos.

| Parâmetro | Tipo   | Descrição               |
|-----------|--------|-------------------------|
| from      | string | Data inicial YYYY-MM-DD |
| to        | string | Data final YYYY-MM-DD   |
| model     | string | `PhoneX Pro`, `PhoneX Lite`, `PhoneX Ultra`, `PhoneX Mini` — omitir retorna fábrica toda |

**Chave sugerida para chamar_api:** `producao`

Colunas relevantes:

| Coluna               | Tipo  | Descrição                          |
|----------------------|-------|------------------------------------|
| date                 | str   | Data YYYY-MM-DD — eixo X           |
| shift_a_efficiency   | int   | Eficiência do turno A em %         |
| shift_b_efficiency   | int   | Eficiência do turno B em %         |
| shift_c_efficiency   | int   | Eficiência do turno C em %         |

> Quando `shift` é omitido na chamada, os três campos são preenchidos com valores reais. Quando um turno é filtrado, apenas o campo daquele turno é preenchido — os demais ficam zerados. **Para comparativo entre turnos, nunca passe `shift`.**

---

### 2. Snapshot atual por turno

`GET /kpis?shift=A` (repetir para B e C)

Retorna KPIs acumulados do dia para o turno selecionado.

**Chave sugerida para chamar_api:** `kpi_a`, `kpi_b`, `kpi_c`

Coluna relevante: `efficiency` (float, %)

---

## Gráfico padrão — histórico dos três turnos (linhas)

Use quando o usuário pedir evolução da eficiência por turno, tendência, comparativo ao longo do tempo.

```python
x_labels = pd.to_datetime(producao['date']).dt.strftime('%d/%m')
n  = len(x_labels)
x  = range(n)

eff_a = producao['shift_a_efficiency'].values.astype(float)
eff_b = producao['shift_b_efficiency'].values.astype(float)
eff_c = producao['shift_c_efficiency'].values.astype(float)

# Zera corretamente — valores 0 indicam dado ausente, não eficiência zero
eff_a = np.where(eff_a == 0, np.nan, eff_a)
eff_b = np.where(eff_b == 0, np.nan, eff_b)
eff_c = np.where(eff_c == 0, np.nan, eff_c)

fig, ax = plt.subplots(figsize=(10, 4))

ax.plot(x, eff_a, color='#60a5fa', linewidth=2,   marker='o', markersize=3, label='Turno A')
ax.plot(x, eff_b, color='#34d399', linewidth=2,   marker='o', markersize=3, label='Turno B')
ax.plot(x, eff_c, color='#f87171', linewidth=2,   marker='o', markersize=3, label='Turno C')
ax.axhline(85,    color='#475569', linestyle='--', linewidth=1.2,           label='Meta 85%')

# Médias por turno
for eff, cor, nome in [(eff_a,'#60a5fa','A'), (eff_b,'#34d399','B'), (eff_c,'#f87171','C')]:
    media = np.nanmean(eff)
    ax.axhline(media, color=cor, linestyle=':', linewidth=0.8, alpha=0.6)
    ax.text(n - 0.5, media, f' {media:.1f}%', color=cor, fontsize=7, va='center')

step = max(1, n // 10)
ax.set_xticks(list(x)[::step])
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)
ax.set_ylim(50, 105)
ax.set_title('Eficiência por Turno — Histórico', color='#1e293b', fontsize=12)
ax.set_ylabel('Eficiência (%)', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — snapshot atual (barras comparativas)

Use quando o usuário quiser ver a eficiência atual de cada turno lado a lado, sem série temporal.

```python
# Pressupõe kpi_a, kpi_b, kpi_c carregados via chamar_api
turnos = ['Turno A', 'Turno B', 'Turno C']
efic   = [float(kpi_a['efficiency'].iloc[0]),
          float(kpi_b['efficiency'].iloc[0]),
          float(kpi_c['efficiency'].iloc[0])]
cores  = ['#60a5fa', '#34d399', '#f87171']
meta   = 85.0

fig, ax = plt.subplots(figsize=(7, 4))
bars = ax.bar(turnos, efic, color=cores, width=0.5, alpha=0.9)

for bar, val in zip(bars, efic):
    ax.text(bar.get_x() + bar.get_width() / 2, val + 0.5,
            f'{val:.1f}%', ha='center', fontsize=10, color='#1e293b')

ax.axhline(meta, color='#475569', linestyle='--', linewidth=1.2, label=f'Meta {meta}%')
ax.set_ylim(0, 110)
ax.set_title('Eficiência por Turno — Atual', color='#1e293b', fontsize=12)
ax.set_ylabel('Eficiência (%)', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — análise estatística entre turnos

Use quando o usuário pedir se a diferença entre turnos é significativa, ou qual turno tem desempenho consistentemente melhor.

```python
# Remove NaN antes dos testes
a = eff_a[~np.isnan(eff_a)]
b = eff_b[~np.isnan(eff_b)]
c = eff_c[~np.isnan(eff_c)]

# ANOVA — diferença global entre os três turnos
f_stat, p_anova = stats.f_oneway(a, b, c)

# Se ANOVA significativa (p < 0.05), comparações par a par
p_ab = stats.ttest_ind(a, b).pvalue
p_ac = stats.ttest_ind(a, c).pvalue
p_bc = stats.ttest_ind(b, c).pvalue

# Inclua os p-values na resposta em linguagem simples:
# "ANOVA p=0.01 — há diferença significativa entre turnos.
#  Turno A vs C: p=0.003 (A consistentemente mais eficiente).
#  Turno A vs B: p=0.18 (sem diferença significativa)."
```

---

## Variantes comuns

| Pedido do usuário                             | Adaptação                                                            |
|-----------------------------------------------|----------------------------------------------------------------------|
| "qual turno é mais eficiente"                 | `np.nanmean` para cada turno e aponte o maior                        |
| "eficiência hoje"                             | Use endpoint `/kpis` + variante snapshot                             |
| "turno C está piorando"                       | Plote apenas `eff_c` com linha de tendência (`np.polyfit`)           |
| "diferença entre turnos é real"               | Use a variante estatística com ANOVA + t-tests par a par             |
| "meta diferente de 85%"                       | Substitua `meta` pelo valor informado                                |

---

## Cores e tema

| Elemento      | Cor              |
|---------------|------------------|
| Turno A       | `#60a5fa`        |
| Turno B       | `#34d399`        |
| Turno C       | `#f87171`        |
| Meta          | `#475569` dashed |
| Médias        | mesma cor + `alpha=0.6` dotted |
| Fundo figure  | `white`        |
| Fundo eixos   | `white`        |
| Texto/ticks   | `#334155`        |
| Título        | `#1e293b`        |
