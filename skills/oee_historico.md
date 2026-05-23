# skill: oee_historico
# descricao: Gráfico de OEE (eficiência global) histórico — linha de OEE com componentes Disponibilidade e Performance, meta e média do período.
# palavras-chave: oee, eficiência global, disponibilidade, performance, availability, histórico, tendência, componentes oee

---

## Endpoint

`GET /production/historical`

---

## Parâmetros da API

| Parâmetro | Tipo   | Valores aceitos | Descrição                                       |
|-----------|--------|-----------------|-------------------------------------------------|
| from      | string | YYYY-MM-DD      | Data inicial do período                         |
| to        | string | YYYY-MM-DD      | Data final do período                           |
| shift     | string | `A`, `B`, `C`   | Turno — omitir retorna média dos três turnos    |
| line      | integer | `1`, `2`, `3`, `4` | Linha de produção — ao filtrar, OEE usa qualidade da linha (FPY) com disponibilidade/performance da fábrica |

**Chave sugerida para chamar_api:** `producao`

---

## Colunas relevantes

| Coluna       | Tipo  | Descrição                                         |
|--------------|-------|---------------------------------------------------|
| date         | str   | Data YYYY-MM-DD — eixo X                          |
| oee          | float | OEE — eficiência global em %                      |
| availability | float | Componente disponibilidade em %                   |
| performance  | float | Componente performance em %                       |

> **Nota:** quando `shift` é omitido, `availability` e `performance` retornam a média dos três turnos. Quando um turno é filtrado, os valores refletem apenas aquele turno.

---

## Gráfico padrão — OEE com componentes

Use quando o usuário pedir OEE histórico, eficiência global, componentes do OEE ou tendência de eficiência.

```python
x_labels = pd.to_datetime(producao['date']).dt.strftime('%d/%m')
n = len(x_labels)
x = range(n)
meta_oee = 85.0  # meta padrão — ajuste se o usuário informar outra

oee   = producao['oee'].values
avail = producao['availability'].values
perf  = producao['performance'].values

fig, ax = plt.subplots(figsize=(10, 4))

# Área sombreada sob OEE
ax.fill_between(x, oee, alpha=0.12, color='#a78bfa')

# Linhas dos três indicadores
ax.plot(x, oee,   color='#a78bfa', linewidth=2.2, label='OEE (%)')
ax.plot(x, avail, color='#60a5fa', linewidth=1.4, linestyle='-',  label='Disponibilidade (%)', alpha=0.85)
ax.plot(x, perf,  color='#fbbf24', linewidth=1.4, linestyle='-',  label='Performance (%)',     alpha=0.85)

# Linha de meta
ax.axhline(meta_oee, color='#475569', linestyle='--', linewidth=1.2, label=f'Meta {meta_oee}%')

# Média OEE do período
media = oee.mean()
ax.axhline(media, color='#94a3b8', linestyle=':', linewidth=1, label=f'Média OEE {media:.1f}%')

# Eixo X espaçado
step = max(1, n // 10)
ax.set_xticks(list(x)[::step])
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)

# Limites Y com margem
y_min = min(oee.min(), avail.min(), perf.min())
ax.set_ylim(max(0, y_min - 4), 105)

# Anotação do OEE mais recente
ax.annotate(
    f'{oee[-1]:.1f}%',
    xy=(n - 1, oee[-1]),
    xytext=(n - 1, oee[-1] + 2),
    color='#a78bfa', fontsize=9, ha='center',
)

ax.set_title('OEE — Eficiência Global', color='#1e293b', fontsize=12)
ax.set_ylabel('(%)', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — OEE por turno (A / B / C comparado)

Use quando o usuário quiser comparar OEE entre turnos. Requer três chamadas API, uma por turno.

```python
# Pressupõe que chamar_api foi chamado três vezes:
# chave='turno_a' com shift=A, 'turno_b' com shift=B, 'turno_c' com shift=C

x_labels = pd.to_datetime(turno_a['date']).dt.strftime('%d/%m')
n = len(x_labels)
x = range(n)

fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(x, turno_a['oee'].values, color='#60a5fa', linewidth=1.8, label='Turno A')
ax.plot(x, turno_b['oee'].values, color='#34d399', linewidth=1.8, label='Turno B')
ax.plot(x, turno_c['oee'].values, color='#f87171', linewidth=1.8, label='Turno C')
ax.axhline(85, color='#475569', linestyle='--', linewidth=1, label='Meta 85%')

step = max(1, n // 10)
ax.set_xticks(list(x)[::step])
ax.set_xticklabels(x_labels[::step], rotation=45, ha='right', fontsize=8)
ax.set_ylim(50, 105)
ax.set_title('OEE por Turno — Comparativo', color='#1e293b', fontsize=12)
ax.set_ylabel('OEE (%)', color='#334155')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variantes comuns

| Pedido do usuário                          | Adaptação                                                         |
|--------------------------------------------|-------------------------------------------------------------------|
| "só o OEE, sem componentes"                | Remova as linhas de `avail` e `perf`                              |
| "meta diferente de 85%"                    | Substitua `meta_oee` pelo valor informado                         |
| "comparar turnos"                          | Use a variante por turno acima                                    |
| "qual componente puxa o OEE para baixo"    | Calcule `[('OEE', oee.mean()), ('Disp.', avail.mean()), ('Perf.', perf.mean())]` e aponte o menor |
| "melhor e pior dia"                        | `producao.loc[producao['oee'].idxmax()]` e `idxmin()`             |

---

## Cores e tema

| Elemento        | Cor                   |
|-----------------|-----------------------|
| OEE             | `#a78bfa`             |
| Área OEE        | `#a78bfa` + `alpha=0.12` |
| Disponibilidade | `#60a5fa`             |
| Performance     | `#fbbf24`             |
| Meta            | `#475569` dashed      |
| Média           | `#94a3b8` dotted      |
| Turno A         | `#60a5fa`             |
| Turno B         | `#34d399`             |
| Turno C         | `#f87171`             |
| Fundo figure    | `white`             |
| Fundo eixos     | `white`             |
| Texto/ticks     | `#334155`             |
| Título          | `#1e293b`             |
