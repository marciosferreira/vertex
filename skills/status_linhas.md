# skill: status_linhas
# descricao: Status em tempo real das linhas de produção — painel visual com estado (running/stopped/maintenance), progresso vs meta, FPY e velocidade de cada linha.
# palavras-chave: status, linhas, running, stopped, maintenance, tempo real, progresso, operador, speed, painel

---

## Endpoint

`GET /lines/status`

Retorna snapshot atual — sem parâmetros de data ou turno.

**Chave sugerida para chamar_api:** `status`

---

## Colunas do DataFrame

| Coluna    | Tipo  | Descrição                                                      |
|-----------|-------|----------------------------------------------------------------|
| id        | int   | Identificador da linha (1–4)                                   |
| name      | str   | Nome da linha (ex: `Linha 1`)                                  |
| model     | str   | Modelo em produção (ex: `PhoneX Pro`)                          |
| status    | str   | Estado atual: `running`, `stopped`, `maintenance`              |
| produced  | int   | Unidades produzidas até o momento                              |
| target    | int   | Meta do dia                                                    |
| fpy       | float | First Pass Yield atual em %                                    |
| speed_pct | int   | Velocidade da linha em % da capacidade nominal                 |
| operator  | str   | Nome do operador responsável                                   |

---

## Gráfico padrão — barras horizontais com status colorido

Use quando o usuário pedir status das linhas, painel de linhas, situação atual ou visão geral.

```python
import numpy as np

cor_status = {
    'running':     '#34d399',
    'stopped':     '#f87171',
    'maintenance': '#fbbf24',
}

nomes    = status['name'].tolist()
prod     = status['produced'].values
metas    = status['target'].values
pct      = (prod / metas * 100).clip(0, 100)
cores    = [cor_status.get(s, '#94a3b8') for s in status['status']]

fig, ax = plt.subplots(figsize=(9, 4))

# Barra de fundo (meta = 100%)
ax.barh(nomes, [100] * len(nomes), color='#1e293b', height=0.5)

# Barra de progresso colorida por status
ax.barh(nomes, pct, color=cores, height=0.5, alpha=0.9)

# Anotações: produzido / meta e FPY
for i, (p, m, f, s) in enumerate(zip(prod, metas, status['fpy'], status['status'])):
    ax.text(101, i, f"{p:,}/{m:,}  FPY {f:.1f}%  [{s}]",
            va='center', fontsize=8, color='#94a3b8')

ax.set_xlim(0, 160)
ax.set_xlabel('% da meta', color='#334155')
ax.set_title('Status das Linhas — Tempo Real', color='#1e293b', fontsize=12)
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.spines[:].set_visible(False)

# Legenda de status
from matplotlib.patches import Patch
legenda = [Patch(color=c, label=s.capitalize()) for s, c in cor_status.items()]
ax.legend(handles=legenda, facecolor='white', labelcolor='#1e293b',
          fontsize=8, loc='lower right')

fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Variante — velocidade das linhas (speed_pct)

Use quando o usuário perguntar sobre ritmo, cadência ou velocidade de cada linha.

```python
cor_status = {
    'running':     '#60a5fa',
    'stopped':     '#f87171',
    'maintenance': '#fbbf24',
}

nomes = status['name'].tolist()
speed = status['speed_pct'].values
cores = [cor_status.get(s, '#94a3b8') for s in status['status']]

fig, ax = plt.subplots(figsize=(9, 3.5))
bars = ax.bar(nomes, speed, color=cores, width=0.5, alpha=0.9)

for bar, val, s in zip(bars, speed, status['status']):
    ax.text(bar.get_x() + bar.get_width() / 2, val + 1,
            f'{val}%', ha='center', fontsize=9, color='#1e293b')

ax.axhline(100, color='#475569', linestyle='--', linewidth=1, label='Capacidade nominal')
ax.set_ylim(0, 115)
ax.set_ylabel('Velocidade (%)', color='#334155')
ax.set_title('Velocidade das Linhas', color='#1e293b', fontsize=12)
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b', fontsize=8)
fig.patch.set_facecolor('white')
plt.tight_layout()
result = fig
```

---

## Tabela de status

Quando o usuário pedir lista, tabela ou resumo das linhas:

```python
cols = ['name', 'model', 'status', 'produced', 'target', 'fpy', 'speed_pct', 'operator']
result = status[cols].rename(columns={
    'name': 'Linha', 'model': 'Modelo', 'status': 'Status',
    'produced': 'Produzido', 'target': 'Meta',
    'fpy': 'FPY (%)', 'speed_pct': 'Vel. (%)', 'operator': 'Operador'
})
```

---

## Variantes comuns

| Pedido do usuário                        | Adaptação                                                          |
|------------------------------------------|--------------------------------------------------------------------|
| "linhas paradas" / "em manutenção"       | Filtre `status[status['status'] == 'stopped']` ou `'maintenance'`  |
| "qual linha está mais próxima da meta"   | `(status['produced'] / status['target']).idxmax()`                 |
| "operador de cada linha"                 | Inclua `operator` na tabela ou como anotação no gráfico            |
| "FPY de cada linha"                      | Use barras verticais com a coluna `fpy`, cor por status            |

---

## Cores e tema

| Elemento       | Cor                    |
|----------------|------------------------|
| `running`      | `#34d399` (barras horiz.) / `#60a5fa` (velocidade) |
| `stopped`      | `#f87171`              |
| `maintenance`  | `#fbbf24`              |
| Fundo barra meta | `#1e293b`            |
| Capacidade nominal | `#475569` dashed   |
| Fundo figure   | `white`              |
| Fundo eixos    | `white`              |
| Texto/ticks    | `#334155`              |
| Título         | `#1e293b`              |
