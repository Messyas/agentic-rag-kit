# Estado da implementação — 04/10/2026

O kit tem implementações funcionais para as etapas descritas no plano. Arquivos
declarativos como `__init__.py` e `py.typed` podem ser intencionalmente mínimos.
Este status distingue código disponível de validação que depende de ambiente e
dados de produção.

## Implementado

| Etapa | Entrega disponível |
|---|---|
| E1–E2 | Modelos imutáveis, estados, erros, portas, settings, registry, packs e container por aplicação |
| E3–E4 | Adaptadores Ollama/OpenAI compatíveis, resiliência, cache de LLM, roteamento/failover e monitor de saúde periódico |
| E5–E6 | Embeddings Ollama/sentence-transformers, cache LRU, pgvector e migrações aditivas |
| E7–E8 | Loaders CSV/XLSX/GERP, schemas, validação, chunkers, indexação transacional, busca densa/léxica/híbrida, reranking e enriquecimento |
| E9–E12 | Grading, prompts versionados, saída estruturada, guardrails, reparos limitados, fluxo corretivo e agente com limites de chamadas, passos, tempo e tokens estimados |
| E13–E14 | Fachada, resultados idempotentes persistidos, lock PostgreSQL por chave, invalidação `STALE`, CLI e pack scrap extensível |
| E15 | Dataset validável, gerador sintético, baselines, braços A0–A5, isolamento de fontes, métricas, intervalos e relatórios |
| E17–E18 | Logs/traces com redação, métricas de recursos, documentação, ADRs, ferramentas de qualidade e wheel |

O `README.md` e [INTEGRATION.md](INTEGRATION.md) descrevem uso local e integração
por portas. O host continua responsável por autenticação, autorização, política
de retenção e composição de API/worker/broker.

## Ainda depende de integração ou evidência externa

- Instalar os modelos configurados (`qwen2.5:7b-instruct-q4_K_M` e `bge-m3`)
  e executar avaliação A0–A5 em dados anonimizados e revisados. O corpus entregue
  é sintético; não demonstra metas de qualidade ou capacidade de produção.
- Calibrar no split dev e publicar avaliação representativa com falhas por
  causa, intervalos, throughput e medições de hardware. Não há inferência real
  nem resultados de qualidade afirmados nesta implementação.
- Preencher few-shot somente com exemplos aprovados e separados do conjunto de
  avaliação. O arquivo está vazio de propósito enquanto não houver exemplos
  revisados disponíveis.
- Validar adapters opcionais no ambiente correspondente; a validação estática
  não substitui os contratos de runtime com Ollama, modelos locais e hardware.
- API, worker Taskiq, gateway, autenticação, autorização, quotas e execução de
  produção precisam ser compostos pelo aplicativo consumidor conforme E20.
- Criar as apresentações e gravações E19 depois de existirem resultados reais.

O Docker local pode receber o schema aditivo com `rag-kit db upgrade`; a operação
não apaga tabelas ou registros existentes. `rag-kit check` verifica prontidão do
ambiente, mas não substitui a avaliação dos modelos.
