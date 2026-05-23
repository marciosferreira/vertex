# skill: producao_por_hora
# descricao: Gráfico de produção por hora — média e desvio padrão por hora do turno, comparativo entre turnos, perfil intradiário com meta e defeitos.
# palavras-chave: hora, horário, intradiário, turno, produção por hora, hourly, desvio padrão, perfil, pico, gargalo

---

## Endpoint

`GET /production/hourly`

Retorna médias agregadas por hora no período. Sempre exige `shift`.

---

## Parâmetros da API

| Parâmetro | Tipo   | Obrigatório | Valores aceitos | Descrição                                    |
|-----------|--------|-------------|-----------------|----------------------------------------------|
| shift     | string | **sim**     | `A`, `B`, `C`   | Turno a consultar                            |
| from      | string | não         | YYYY-MM-DD      | Data inicial — padrão: últimos 7 dias        |
| to        | string | não         | YYYY-MM-DD      | Data final — padrão: últimos 7 dias          |
| line      | integer | não        | `1`, `2`, `3`, `4`                                         | Filtra por linha de produção — omitir retorna agregado de todas     |

**Chave sugerida para chamar_api:** `hora_a`, `hora_b`, `hora_c` (uma por turno consultado)

---

## Horas por turno

| Turno | Horas                                      |
|-------|--------------------------------------------|
| A     | 06h, 07h, 08h, 09h, 10h, 11h, 12h, 13h   |
| B     | 14h, 15h, 16h, 17h, 18h, 19h, 20h, 21h   |
| C     | 22h, 23h, 00h, 01h, 02h, 03h, 04h, 05h   |

---

## Colunas do DataFrame

| Coluna           | Tipo  | Descrição                                               |
|------------------|-------|---------------------------------------------------------|
| hour             | str   | Hora no formato `HHh` (ex: `06h`) — eixo X             |
| avg_produced     | float | Média de unidades produzidas nessa hora no período      |
| stddev_produced  | float | Desvio padrão da produção — indica variabilidade        |
| avg_defects      | float | Média de defeitos nessa hora                            |
| stddev_defects   | float | Desvio padrão dos defeitos                              |
| avg_target       | float | Meta média por hora                                     |

---

## Gráfico padrão — perfil intradiário de um turno

Use quando o usuário pedir produção por hora, perfil do turno, pico de produção ou hora de menor rendimento.

```python
horas    = hora_a['hour'].tolist()
avg      = hora_a['avg_produced'].values
std      = hora_a['stddev_produced'].values
meta     = hora_a['avg_target'].values
defeitos = hora_a['avg_defects'].values
x        = range(len(horas))

fig, ax = plt.subplots(figsize=(10, 4))

# Banda de desvio padrão (variabilidade)
ax.fill_between(x, avg - std, avg + std, alpha=0.15, color='#60a5fa', label='±1 desvio padrão')

# Linha de produção média
ax.plot(x, avg, color='#60a5fa', linewidth=2, marker='o', markersize=4, label='Média produzida')

# Linha de meta por hora
ax.plot(x, meta, color='#475569', linestyle='--', linewidth=1.2, label='Meta/hora')

# Barras de defeitos em eixo secundário
ax2 = ax.twinx()
ax2.bar(x, defeitos, color='#f87171', alpha=0.4, width=0.4, label='Defeitos (média)')
ax2.set_ylabel('Defeitos', color='#f87171')
ax2.tick_params(colors='#f87171')
ax2.set_facecolor('white')

# Destaque da hora de pico
pico_idx = int(avg.argmax())
ax.annotate(
    f'Pico\n{avg[pico_idx]:.0f} un.',
    xy=(pico_idx, avg[pico_idx]),
    xytext=(pico_idx, avg[pico_idx] + std.max() + 10),
    color='#60a5fa', fontsize=8, ha='center',
    arrowprops=dict(arrowstyle='->', color='#60a5fa', lw=1),
)

ax.set_xticks(list(x))
ax.set_xticklabels(horas, fontsize=9)
ax.set_title('Produção por Hora — Turno A', color='#1e293b', fontsize=12)
ax.set_ylabel('Unidades produzidas', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')

# Legenda combinada dos dois eixos
lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2,
          facecolor='white', labelcolor='#1e293b', fontsize=8)

fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

> Substitua `hora_a` e `'Turno A'` pelo turno solicitado. As horas do eixo X já estão ordenadas corretamente pela API.

---

## Variante — comparativo entre turnos

Use quando o usuário quiser comparar o perfil de produção entre turnos A, B e C. Requer três chamadas API.

```python
# Pressupõe hora_a, hora_b, hora_c carregados via chamar_api
fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=False)

dados = [
    (hora_a, 'Turno A', '#60a5fa'),
    (hora_b, 'Turno B', '#34d399'),
    (hora_c, 'Turno C', '#f87171'),
]

for ax, (df, nome, cor) in zip(axes, dados):
    horas = df['hour'].tolist()
    avg   = df['avg_produced'].values
    std   = df['stddev_produced'].values
    meta  = df['avg_target'].values
    x     = range(len(horas))

    ax.fill_between(x, avg - std, avg + std, alpha=0.15, color=cor)
    ax.plot(x, avg,  color=cor,      linewidth=2, marker='o', markersize=3, label='Média')
    ax.plot(x, meta, color='#475569', linestyle='--', linewidth=1, label='Meta')
    ax.set_xticks(list(x))
    ax.set_xticklabels(horas, fontsize=8)
    ax.set_title(nome, color='#1e293b', fontsize=10)
    ax.set_ylabel('Unidades', color='#334155')
    ax.set_facecolor('white')
    ax.tick_params(colors='#334155')
    ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=7)

fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variantes comuns

| Pedido do usuário                          | Adaptação                                                                  |
|--------------------------------------------|----------------------------------------------------------------------------|
| "hora com mais defeitos"                   | `hora_a.loc[hora_a['avg_defects'].idxmax(), 'hour']`                       |
| "hora mais inconsistente"                  | `hora_a.loc[hora_a['stddev_produced'].idxmax(), 'hour']` — maior desvio   |
| "hora abaixo da meta"                      | `hora_a[hora_a['avg_produced'] < hora_a['avg_target']]`                   |
| "sem defeitos no gráfico"                  | Omita o `ax2` e a barra de defeitos                                        |
| "comparar turnos"                          | Use a variante comparativo acima                                           |

---

## Cores e tema

| Elemento              | Cor                      |
|-----------------------|--------------------------|
| Turno A / linha prod. | `#60a5fa`                |
| Turno B               | `#34d399`                |
| Turno C               | `#f87171`                |
| Banda desvio padrão   | mesma cor + `alpha=0.15` |
| Meta/hora             | `#475569` dashed         |
| Defeitos (barras)     | `#f87171` + `alpha=0.4`  |
| Fundo figure          | `white`                |
| Fundo eixos           | `white`                |
| Texto/ticks           | `#334155`                |
| Título                | `#1e293b`                |
