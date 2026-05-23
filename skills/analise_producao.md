# skill: analise_producao
# descricao: Dados de produção diária vs meta por linha e turno, incluindo defeitos e FPY.
# palavras-chave: produção, meta, análise, eficiência, tendência, linha, turno, defeitos, fpy, oee

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
| date               | str   | Data no formato YYYY-MM-DD — use sempre como eixo X    |
| label              | str   | Dia da semana abreviado (ex: `Dom`, `Seg`, `Ter`). **NÃO usar como eixo X** — repete a cada 7 dias e causa duplicação de pontos no gráfico |
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

---

## Ambiente de execução

O script em `analisar_dataframe` tem acesso às seguintes bibliotecas pré-importadas:

| Variável | Biblioteca       | Uso principal                                      |
|----------|------------------|----------------------------------------------------|
| `pd`     | pandas           | DataFrames, filtros, agregações                    |
| `np`     | numpy            | Operações numéricas                                |
| `plt`    | matplotlib.pyplot| Geração de gráficos                                |
| `stats`  | scipy.stats      | Testes estatísticos                                |

### Análises estatísticas disponíveis via `stats`

| Necessidade                        | Função                            |
|------------------------------------|-----------------------------------|
| Comparar dois turnos (médias)      | `stats.ttest_ind(a, b)`           |
| Comparar três turnos               | `stats.f_oneway(a, b, c)`         |
| Não-paramétrico (distribuição livre)| `stats.mannwhitneyu(a, b)`       |
| Correlação linear                  | `stats.pearsonr(x, y)`            |
| Correlação por ranking             | `stats.spearmanr(x, y)`           |
| Verificar normalidade              | `stats.shapiro(x)`                |

Use análise estatística sempre que o usuário pedir comparações entre turnos, linhas
ou períodos, ou quando quiser validar se uma diferença observada é significativa.
Inclua o p-value na resposta e interprete em linguagem simples (ex: "diferença
estatisticamente significativa com p=0.02").

---

## Geração de gráficos

### Quando gerar gráfico vs tabela

| O usuário diz...                              | Você deve...             |
|-----------------------------------------------|--------------------------|
| "gráfico", "chart", "plot", "visualização"    | gerar SOMENTE o gráfico  |
| "tabela", "lista", "dados"                    | gerar SOMENTE a tabela   |
| "gráfico e tabela" / "relatório completo"     | gerar os dois            |
| nada específico (análise genérica)            | gráfico + resumo em texto|

**NUNCA substitua um gráfico por uma tabela quando o usuário pedir um gráfico.**
Se o usuário usou as palavras "gráfico", "chart", "plot" ou "visualize", o resultado
DEVE conter um `result = fig`. Retornar apenas uma tabela nesse caso é considerado
uma resposta errada.

O ambiente de execução disponibiliza `plt` (matplotlib.pyplot) e `pd` (pandas).
Para gerar um gráfico, atribua a figura à variável `result`:

```python
# Eixo X: sempre usar 'date' formatado como DD/MM — 'label' repete a cada 7 dias
x = pd.to_datetime(producao['date']).dt.strftime('%d/%m')
fig, ax = plt.subplots(figsize=(9, 4))
ax.bar(x, producao['produced'], color='#60a5fa', label='Produzido')
ax.bar(x, producao['defects'],  color='#f87171', label='Defeitos')
ax.plot(x, producao['target'],  color='#475569', linestyle='--', label='Meta')
ax.set_facecolor('white')
ax.tick_params(colors='#334155')
ax.legend(facecolor='white', labelcolor='#1e293b')
plt.xticks(rotation=45, ha='right')
fig.patch.set_facecolor('white')
result = fig
```

- **Eixo X sempre usa `date` formatado**: `pd.to_datetime(df['date']).dt.strftime('%d/%m')`. Nunca use `label` como eixo X — é dia da semana e se repete a cada 7 dias, causando dois pontos Y por X.
- Atribuir `result = fig` é suficiente — o sistema salva e exibe o gráfico automaticamente.
- Use `facecolor='white'` no figure e nos eixos para manter o tema escuro do dashboard.
- Cores recomendadas: produzido `#60a5fa`, defeitos `#f87171`, meta `#475569` (dashed),
  FPY/verde `#34d399`, OEE/roxo `#a78bfa`, amarelo `#fbbf24`.
- Gráfico e tabela podem coexistir: chame `analisar_dataframe` duas vezes — uma para
  a tabela (result = df) e outra para o gráfico (result = fig).
- Sempre feche os eixos desnecessários e use `bbox_inches='tight'` implícito (já configurado).
