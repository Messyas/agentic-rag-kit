# Validação com a exportação anonimizada do Hanaro

Data: 04/10/2026. Fonte: `Other_Account_Transaction_Text_anonymized`, fixture do
Hanaro. SHA-256: `e3a39525ffed6f65f5c3f815605716352f01819ba5599bb17652ea111ca07643`.
Os dados são transações reais anonimizadas; não há gabarito humano de causas ou
relatórios nesse arquivo.

## Benchmark concluído

O loader aceitou **1.063 de 1.063 linhas**, com aderência de colunas de 100%.
A amostra contém 12 linhas, selecionadas de maneira determinística por
organização, sinal financeiro e presença de comentário. Cada linha originou
uma análise de ocorrência e um dossier: **24 solicitações por braço**.
Os 12 casos cobrem as quatro organizações, seis valores negativos e seis não
negativos, com sete comentários preenchidos e cinco vazios.
O baseline utiliza o mesmo compositor com resposta vazia de modelo e fatos
determinísticos; não representa um relatório escrito manualmente por analista.

Modelo local: `qwen2.5:7b-instruct-q4_K_M`. Limite: 90 segundos por solicitação.
A execução concluída ocorreu fora do sandbox após erros de ACL no ambiente.
Os resultados anteriores e esta nova execução não são medidas controladas do
efeito do sandbox na latência.

| Medida | Baseline determinístico | RAG local |
|---|---:|---:|
| Solicitações concluídas | 24/24 | 23/24 |
| Falhas / timeouts | 0 | 1 timeout após 90 s |
| Schema e referências válidas entre respostas concluídas | 24/24 | 23/23 |
| Citações literais, escopo e nenhuma causa confirmada entre respostas concluídas | 24/24 | 23/23 |
| Respostas contendo afirmações verificáveis | 20/24 | 21/24 |
| Afirmações produzidas | 32 | 34 |
| Respostas com hipóteses 4M | 0/24 | 6/23 concluídas |
| `COMPLETE` / `INSUFFICIENT_EVIDENCE` | 0 / 24 | 5 / 18 concluídas |
| Latência média; p95 (respostas concluídas) | 0,0015 / 0,0028 s | 7,13 / 16,75 s |
| Latência média da análise / dossier (concluídas) | 0,0017 / 0,0012 s | 3,90 / 10,09 s* |

## Métricas adicionais aplicáveis (rodada 2026-10-04)

Além do benchmark inicial acima, foi implementada e executada uma rodada com **12 linhas, 24
casos únicos por braço e duas repetições**. Ela calcula campos transacionais
exatos (acurácia, precisão, recall e F1), consistência da saída entre repetições,
p95 por tipo de solicitação, throughput de tokens, pico de memória residente da
aplicação e do processo Ollama, e taxa de falhas. O escore de campos cobre apenas
`item_description` e `requisition_comment` copiados literalmente; não avalia a
qualidade narrativa ou das causas 4M. O throughput é completion tokens dividido
pela duração total reportada pelo Ollama, que inclui o processamento do prompt.

Os resultados completos, incluindo manifesto e medições por caso sem narrativas,
estão em [metrics](../evaluation/reports/hanaro-validation-20261004/metrics/manifest.json)
e no [resumo versionado](RESUMO_METRICAS_HANARO.md).
Essa rodada teve zero falhas e timeout de 90 s por chamada. Uma segunda tentativa
para persistir duração do Ollama em cada caso foi interrompida após timeouts
repetidos. Portanto, tokens/s está instrumentado no código, mas não tem resultado
completo reportável nesta validação. A duração disponível na execução parcial
não foi misturada aos resultados completos.

As métricas de acurácia/precisão/recall/F1 de causas 4M continuam sem cálculo:
seria necessário rotular causas esperadas por analistas. Tool-call accuracy não
se aplica ao fluxo RAG atual, que não chama ferramentas. “Utilidade para o
analista” também requer revisão cega humana; não é inferida por validade do
schema ou de citações.

As checagens de citações também passam quando a resposta não contém afirmações.
Por isso a cobertura de respostas com afirmações aparece separadamente: no RAG,
21 dos 23 casos concluídos continham ao menos uma afirmação; dois passaram nas
checagens por não terem afirmações para conferir. A latência média do RAG exclui
o timeout; na análise, também exclui esse caso.
A existência de uma citação literal não comprova que a interpretação causal
esteja correta. `COMPLETE` indica suficiência do rascunho segundo o compositor;
não significa aprovação humana ou confirmação de causa.

O benchmark permite conferir formato, referências, escopo, incerteza e tempo.
**Não mede precisão/recall dos 4Ms ou utilidade da narrativa**, pois faltam
rótulos humanos e avaliação independente. A amostra é pequena, com apenas uma
execução por solicitação; não permite estimar confiabilidade de produção.
Houve um timeout no fluxo de análise da ocorrência. Uma amostra piloto de seis
linhas, executada antes da ampliação, concluiu 12/12 solicitações sem timeout;
os resultados dessa execução estão em [pilot-6](../evaluation/reports/hanaro-validation-20261004/pilot-6/manifest.json).
A ocorrência do timeout na amostra ampliada mostra que a estabilidade em lotes
maiores ainda precisa ser medida.

## Casos e testes adicionados

O comando `draft eval-data` gera casos diretamente da fixture, mantendo o hash
da fonte e os índices selecionados. Os resultados arquivados não incluem
comentários, nomes, valores financeiros ou narrativas da exportação.

- [Manifest da execução concluída](../evaluation/reports/hanaro-validation-20261004/manifest.json).
- [Resultados por caso do RAG](../evaluation/reports/hanaro-validation-20261004/local_rag.jsonl).
- [Resultados por caso do baseline](../evaluation/reports/hanaro-validation-20261004/rule_baseline.jsonl).
- [Lista dos 24 casos para rotulagem humana](../evaluation/reports/hanaro-validation-20261004/cases.jsonl).

Foram adicionados nove testes de regressão: fonte inexistente, citação inventada,
versão incorreta, identidade contendo dois-pontos, causa confirmada sem revisão,
fonte de dossier não selecionada, amostragem estratificada, entrada vazia e limite
inválido. A validação dos quatro arquivos de teste do módulo passou com **22
testes**. Ruff, Pyright e os seis contratos do import-linter passaram.
Os testes também detectaram e permitiram corrigir a precedência da rejeição de
um draft `STALE`: ele é recusado como desatualizado antes da validação de aceite.

## Reproduzir

```powershell
.venv/Scripts/python.exe -m rag_kit.interfaces.cli draft eval-data '..\hanaro\automation\fixtures\Other_Account_Transaction_Text_anonymized' --limit 12 --repetitions 2 --output evaluation/runs/hanaro-draft-eval
.venv/Scripts/pytest.exe tests/unit/test_hanaro_draft_eval.py tests/unit/test_scrap_draft_flow.py tests/unit/test_scrap_host_mapping.py tests/unit/test_scrap_period_close.py -q
```

Para validar qualidade causal, rotular os casos com analistas, congelar as
revisões humanas autorizadas como corpus separado e avaliar em amostra
independente. A lista de casos tem `label_status=UNLABELED` para tornar explícito
que os rótulos de causa ainda não existem.
