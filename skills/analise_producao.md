# skill: analise_producao
# descricao: Análise de produção diária vs meta — instrui como chamar a API e interpretar o JSON.
# palavras-chave: produção, meta, análise, eficiência, tendência, linha, turno, produced, target

---

## Instruções para o sub-agente analista

Você deve analisar os dados de produção diária vs meta. Siga este passo a passo:

### Passo 1 — Buscar os dados

Chame a API com:

```
chamar_api(url="http://localhost:8000/production")
```

Para filtrar por período específico, use os parâmetros opcionais:

```
chamar_api(url="http://localhost:8000/production", params={"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"})
```

### Passo 2 — Entender o JSON retornado

A API retorna uma lista de objetos, um por dia:

```json
[
  { "date": "2026-05-09", "produced": 1820, "target": 1900 },
  { "date": "2026-05-10", "produced": 1950, "target": 1900 }
]
```

Campos:
- `date`: data do registro (YYYY-MM-DD)
- `produced`: unidades produzidas no dia
- `target`: meta diária de unidades

### Passo 3 — Analisar os dados

Para cada dia, calcule:
- **% atingimento** = (produced / target) × 100
- **gap** = produced − target (negativo = abaixo da meta)

Depois identifique:
- Total produzido vs total meta no período
- Percentual médio de atingimento
- Dias abaixo da meta e o respectivo gap
- Tendência: a produção está subindo, caindo ou estável?
- O melhor e o pior dia do período

### Passo 4 — Fazer a análise e retornar o resultado final

Você é responsável por fazer a análise completa. Não delegue isso a ninguém.
Após receber o JSON da API, use seu próprio raciocínio para calcular os indicadores
e escrever o texto de análise. O orquestrador irá apenas repassar sua resposta ao
usuário sem modificá-la.

Sua resposta deve ser autocontida e incluir:
- O período analisado (primeira e última data do JSON)
- Total produzido vs total meta
- Percentual médio de atingimento
- Destaque dos dias abaixo da meta (se houver) com o gap de cada um
- Tendência observada no período
- Uma conclusão com insight acionável

Regras:
- Use apenas os valores reais que vieram do JSON — nunca invente números
- Seja direto e objetivo; evite introduções genéricas
- Se o JSON estiver vazio, responda: "Sem dados de produção para o período solicitado."
