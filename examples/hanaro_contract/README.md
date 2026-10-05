# Dados sintéticos para demonstrar a fila local

`demo_scrap.csv` contém quatro ocorrências inventadas. `demo_reviews.jsonl` contém análises humanas fictícias para testar a recuperação de contexto; não são dados nem conclusões do Hanaro.

```powershell
python scripts/build_demo_spreadsheets.py
rag-kit draft batch examples/hanaro_contract/demo_scrap.csv --reviews examples/hanaro_contract/demo_reviews.jsonl --limit 4
rag-kit ingest evaluation/runs/demo_scrap.xlsx --output evaluation/runs/xlsx-ingestion
rag-kit draft queue
rag-kit draft show ID_DO_JOB
rag-kit draft review ID_DO_JOB --decision ACCEPTED
rag-kit draft eval --output evaluation/runs/draft-eval
```

O comando `batch` gera automaticamente rascunhos de análise e de dossiê e grava a fila em `evaluation/runs/drafts.sqlite3`. Reexecutar o mesmo lote reutiliza as mesmas chaves de job. O modelo local deve estar disponível no endpoint configurado por `RAGKIT_OLLAMA__HOST`.

A classificação 4M requer verificação humana: casos similares não provam a causa da ocorrência atual. A quarta linha deliberadamente tem comentário genérico para testar lacunas e abstenção. A saída nesta pasta é uma PoC local, não uma escrita no Hanaro.

Comandos úteis: `draft submit request.json` recebe um contrato de host já autorizado;
`draft run` processa jobs pendentes; `draft show` exibe sugestões, fontes, 4Ms e lacunas;
`draft review` aceita, rejeita ou devolve o item para informações. Rascunhos com evidência
insuficiente não podem ser aceitos. O comando `draft eval` compara uma regra determinística
com o RAG local, grava manifest e resultados JSONL e mede latência e RAM do processo.
