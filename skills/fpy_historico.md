# skill: fpy_historico
# descricao: Gráfico de First Pass Yield (FPY) histórico — linha de tendência com área sombreada, meta e anotação do valor médio.
# palavras-chave: fpy, first pass yield, qualidade, histórico, tendência, gráfico, defeitos, yield

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
| model     | string | `PhoneX Pro`, `PhoneX Lite`, `PhoneX Ultra`, `PhoneX Mini` | Modelo do aparelho — omitir retorna todos (fábrica) |

**Chave sugerida para chamar_api:** `producao`

---

## Colunas relevantes

| Coluna   | Tipo  | Descrição                                         |
|----------|-------|---------------------------------------------------|
| date     | str   | Data no formato YYYY-MM-DD — eixo X do gráfico    |
| fpy      | float | First Pass Yield em % (sem defeitos / total)      |
| produced | int   | Total produzido no dia                            |
| defects  | int   | Total de defeitos no dia                          |

---

## Gráfico padrão — FPY histórico

Gere sempre que o usuário pedir histórico de FPY, qualidade ao longo do tempo, tendência de yield ou variações similares.

```python
import numpy as np

x_dates = pd.to_datetime(producao['date'])
x_labels = x_dates.dt.strftime('%d/%m')
y = producao['fpy'].values
meta_fpy = 95.0  # meta padrão — ajuste se o usuário informar outra

fig, ax = plt.subplots(figsize=(10, 4))

# Área sombreada sob a linha
ax.fill_between(range(len(x_labels)), y, alpha=0.15, color='#34d399')

# Linha principal FPY
ax.plot(range(len(x_labels)), y, color='#34d399', linewidth=2, label='FPY (%)')

# Linha de meta
ax.axhline(meta_fpy, color='#fbbf24', linestyle='--', linewidth=1.2, label=f'Meta {meta_fpy}%')

# Média do período
media = np.mean(y)
ax.axhline(media, color='#94a3b8', linestyle=':', linewidth=1, label=f'Média {media:.1f}%')

# Eixo X com ticks espaçados para não poluir
step = max(1, len(x_labels) // 10)
ax.set_xticks(range(0, len(x_labels), step))
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)

# Limites Y com margem
ax.set_ylim(max(0, y.min() - 3), min(100, y.max() + 3))

# Anotação do valor mais recente
ax.annotate(
    f'{y[-1]:.1f}%',
    xy=(len(x_labels) - 1, y[-1]),
    xytext=(len(x_labels) - 1, y[-1] + 1.5),
    color='#34d399',
    fontsize=9,
    ha='center',
)

ax.set_title('First Pass Yield — Histórico', color='#1e293b', fontsize=12)
ax.set_ylabel('FPY (%)', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variantes comuns

| Pedido do usuário                          | Adaptação                                               |
|--------------------------------------------|----------------------------------------------------------|
| Por turno A / B / C                        | Passe `shift` na API; label da legenda muda para turno  |
| Comparar dois períodos                     | Duas chamadas API → dois `ax.plot` com cores diferentes |
| Meta diferente de 95 %                     | Substitua `meta_fpy` pelo valor informado               |
| Mostrar defeitos no mesmo gráfico          | Adicione eixo secundário `ax2 = ax.twinx()` com barras  |

---

## Cores e tema

| Elemento       | Cor        |
|----------------|------------|
| Linha FPY      | `#34d399`  |
| Área sombreada | `#34d399` + `alpha=0.15` |
| Meta           | `#fbbf24`  |
| Média          | `#94a3b8`  |
| Fundo figure   | `white`  |
| Fundo eixos    | `white`  |
| Texto/ticks    | `#334155`  |
| Título/labels  | `#1e293b`  |
