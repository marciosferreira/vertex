# skill: analise_producao
# descricao: Dados de produção diária vs meta por linha e turno.
# palavras-chave: produção, meta, análise, eficiência, tendência, linha, turno, produced, target

---

## API

**Endpoint:** `GET http://localhost:8000/production`

**Parâmetros opcionais:**

| Parâmetro | Tipo   | Exemplo    | Descrição                  |
|-----------|--------|------------|----------------------------|
| from      | string | 2026-05-01 | Data inicial (YYYY-MM-DD)  |
| to        | string | 2026-05-15 | Data final (YYYY-MM-DD)    |
| shift     | string | A, B ou C  | Filtro por turno           |
| line      | int    | 1, 2, 3, 4 | Filtro por linha           |

**Chave sugerida:** producao

---

## Colunas do DataFrame

| Coluna   | Tipo | Descrição                  |
|----------|------|----------------------------|
| date     | str  | Data no formato YYYY-MM-DD |
| produced | int  | Unidades produzidas no dia |
| target   | int  | Meta diária de unidades    |
