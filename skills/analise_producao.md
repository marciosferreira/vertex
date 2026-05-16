# skill: analise_producao
# descricao: Dados de produção diária vs meta por linha e turno, incluindo defeitos e FPY.
# palavras-chave: produção, meta, análise, eficiência, tendência, linha, turno, defeitos, fpy, oee

---

## Endpoint

`GET http://localhost:8000/production/historical`

---

## Parâmetros da API

| Parâmetro | Tipo   | Valores aceitos | Descrição                                       |
|-----------|--------|-----------------|-------------------------------------------------|
| from      | string | YYYY-MM-DD      | Data inicial do período                         |
| to        | string | YYYY-MM-DD      | Data final do período                           |
| shift     | string | `A`, `B`, `C`   | Turno — omitir retorna agregado dos três turnos |

**Chave sugerida para chamar_api:** `producao`

---

## Filtro por turno

O filtro é aplicado **na API**, não no DataFrame. Passe `shift` nos `params` de `chamar_api`.
Nunca tente filtrar turno no DataFrame após o carregamento.

| Valor | Comportamento                                                              |
|-------|----------------------------------------------------------------------------|
| `A`   | Retorna dados do turno A. `shift_a_efficiency` preenchido, B e C zerados. |
| `B`   | Retorna dados do turno B. `shift_b_efficiency` preenchido, A e C zerados. |
| `C`   | Retorna dados do turno C. `shift_c_efficiency` preenchido, A e B zerados. |
| omitir| Retorna agregado diário com os três turnos somados.                        |

---

## Colunas do DataFrame

| Coluna             | Tipo  | Descrição                                              |
|--------------------|-------|--------------------------------------------------------|
| date               | str   | Data no formato YYYY-MM-DD                             |
| label              | str   | Rótulo curto do dia (ex: `Dom`, `Seg`, `Ter`)          |
| produced           | int   | Unidades produzidas no dia                             |
| defects            | int   | Unidades com defeito no dia                            |
| target             | int   | Meta diária de unidades                                |
| fpy                | float | First Pass Yield em % (sem defeitos / total)           |
| oee                | float | OEE — eficiência global em %                           |
| availability       | float | Componente disponibilidade do OEE em %                 |
| performance        | float | Componente performance do OEE em %                     |
| line1              | int   | Produção da linha 1                                    |
| line2              | int   | Produção da linha 2                                    |
| line3              | int   | Produção da linha 3                                    |
| line4              | int   | Produção da linha 4                                    |
| shift_a_efficiency | float | Eficiência do turno A em % (0 se shift≠A foi filtrado) |
| shift_b_efficiency | float | Eficiência do turno B em % (0 se shift≠B foi filtrado) |
| shift_c_efficiency | float | Eficiência do turno C em % (0 se shift≠C foi filtrado) |
| defect_screen      | int   | Defeitos de tela                                       |
| defect_camera      | int   | Defeitos de câmera                                     |
| defect_battery     | int   | Defeitos de bateria                                    |
| defect_other       | int   | Outros defeitos                                        |
