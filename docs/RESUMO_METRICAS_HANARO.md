# Resumo das métricas avaliadas no Hanaro

Data da execução: 04/10/2026. O benchmark usou a exportação anonimizada
`Other_Account_Transaction_Text_anonymized` e o modelo local
`qwen2.5:7b-instruct-q4_K_M`. O loader aceitou 1.063/1.063 linhas, com 100% de
aderência ao layout. Foram selecionadas 12 linhas estratificadas; cada linha
gerou um caso de análise e um de relatório, executados duas vezes: 48 chamadas
por braço e 24 grupos para medir repetibilidade. O timeout por chamada foi 90 s.

## Resultados

| Métrica | Baseline determinístico | RAG local |
|---|---:|---:|
| Chamadas concluídas / total | 48/48 | 48/48 |
| Falhas e timeouts | 0 | 0 |
| Média de latência | 0,00132 s | 5,9015 s |
| p95 da latência | 0,00190 s | 16,3919 s |
| Schema válido | 48/48 | 48/48 |
| IDs de citação válidos | 48/48 | 48/48 |
| Citações literais | 48/48 | 48/48 |
| Escopo das fontes válido | 48/48 | 48/48 |
| Nenhuma causa 4M marcada como confirmada | 48/48 | 48/48 |
| Campos transacionais exatos: TP / FP / FN | 64 / 0 / 0 | 64 / 0 / 0 |
| Acurácia / precisão / recall / F1 dos campos | 100% / 100% / 100% / 100% | 100% / 100% / 100% / 100% |
| Consistência idêntica entre as duas repetições | 24/24 (100%) | 8/24 (33,3%) |
| Pico de RAM residente (app + Ollama) | 0,109 GB | 0,542 GB |
| Tokens de conclusão | 0 | 18.201 |

Os campos pontuados são somente cópias literais de `item_description` e
`requisition_comment`. Os números de acurácia, precisão, recall e F1 não medem
classificação de causa. Consistência compara a assinatura da saída estruturada,
ignorando metadados de execução. O baseline usa o mesmo compositor com resposta
vazia do modelo; não equivale a um relatório produzido por analista.

## Métricas sem resultado nesta execução

Tokens por segundo foi adicionado à instrumentação, mas não pôde ser reportado
no benchmark completo: a execução não persistiu a duração do Ollama por caso.
Uma tentativa subsequente para capturá-la sofreu timeouts repetidos e foi
interrompida; esses dados parciais não foram misturados à tabela.

Precisão/recall/F1 das causas 4M exigem rótulos esperados revisados por analistas,
que não existem na exportação. Utilidade narrativa e adequação para aprovação
exigem revisão cega humana. Acurácia de chamada de ferramentas não se aplica,
pois esse fluxo RAG não utiliza ferramentas.

## Artefatos

- [Manifesto agregado](../evaluation/reports/hanaro-validation-20261004/metrics/manifest.json)
- [Resultados do RAG por caso](../evaluation/reports/hanaro-validation-20261004/metrics/local_rag.jsonl)
- [Resultados do baseline por caso](../evaluation/reports/hanaro-validation-20261004/metrics/rule_baseline.jsonl)
- [Relatório técnico completo](../docs/VALIDACAO_HANARO.md)
