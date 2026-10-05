# Integração em outros sistemas

O ponto de entrada é `AnalysisFacade`. O domínio descreve fontes, documentos,
perguntas e resultados; o pack fornece a interpretação do domínio de negócio.
O núcleo não importa Hanaro, frameworks HTTP ou clientes de banco de dados.

## Uso do pack scrap

```python
from packs.scrap import build_pack
from rag_kit.bootstrap.container import Container
from rag_kit.bootstrap.settings import Settings


async def analisar(ocorrencia, revisoes, metrics):
    async with Container(Settings()) as container:
        facade = container.build_facade(
            pack=build_pack(),
            pipeline_name="corrective_rag",
            extras={"metrics": metrics},
        )
        await facade.index_records(revisoes)
        return await facade.analyze_record(ocorrencia)
```

As revisões precisam de `review_id` ou `id`, `status="REVIEWED"` e texto em
`title`, `description` ou `cause_description`. A ocorrência precisa de
`occurrence_id` estável. `content_hash` ou `version` identifica sua revisão.
Não indexe a resposta da própria IA como revisão humana.

O adaptador aceita os campos canônicos do Hanaro, incluindo `organization_code`,
`receipt_department`, `transaction_date`, `item_description`, `issue_quantity`,
`issue_amount_brl` e `requisition_comment`. Quantidades e valores financeiros
devem chegar como `Decimal` ou strings decimais, preservando o sinal.
O TSV GERP é carregado preservando os dois campos Description, CP1252, campos
expandidos do comentário e identificação da linha. Reconciliação de identidade,
classificação de componentes e conversão cambial continuam pertencendo ao host.

`metrics` implementa o protocolo assíncrono `ScrapMetricsPort`:
`summary`, `trend` e `top_drivers`. Os totais vêm desse serviço determinístico.
`CsvMetricsAdapter` é uma alternativa para snapshots locais: a última entrada
de cada `occurrence_id` prevalece, registros inativos são excluídos e
`to_be_counted` controla quais valores entram nas somas. Esse adaptador espera
registros ordenados por revisão; não estabelece a ordem a partir de hashes.

## Outro domínio

Implemente `PackSpec` com:

- Modelo Pydantic de saída com `claims()` e `figures_list()`.
- Campos `outcome`, `context`, `hypotheses`, `gaps` e `figures` compatíveis com
  os guardrails comuns; `outcome` é `complete` ou `insufficient_evidence`.
- `subject_from_record`, `record_to_document` e `query_builder`.
- Fatos e números determinísticos, ferramentas tipadas e guardrails específicos.
- Templates versionados `generator.v1.jinja`, `grader.v1.jinja` e
  `agent_system.v1.jinja`. O pipeline corretivo também usa `reformulate.v1.jinja`.
- Mapeamento de colunas e carregadores especiais, quando houver.

Passe o pack diretamente a `build_facade`. Para distribuição independente,
publique a fábrica em um entry point do grupo `rag_kit.packs`:

```toml
[project.entry-points."rag_kit.packs"]
maintenance = "my_system.rag_pack:build_pack"
```

Selecione-o com `RAGKIT_PACK__NAME=maintenance`. Para alterar o vocabulário de
scrap, use `build_pack(defect_types_path=...)`, mantendo a categoria `OTHER`.
Vocabulários de IDs específicos do backend exigem um mapeamento fornecido pelo host.

## Adaptadores e ciclo de vida

`build_facade(..., extras=...)` aceita `metrics`, `retriever`, `runs`, `events`
e `chunker`. `runs` implementa `RunRepository`; `events` implementa `EventBus`.
A persistência de resultados é opcional. A chave considera identidade e revisão
do assunto, pack, pipeline, configuração, schema e conteúdo dos prompts.
O repositório PostgreSQL padrão serializa análises pela chave de idempotência e
persiste resultados concluídos. Alterações ou remoções de fontes indexadas
marcam resultados dependentes como `STALE`. Repositórios fornecidos pelo host
implementam `lock`, `find` e `save` para manter o mesmo contrato.

Para substituir também LLM, embeddings e armazenamento, componha diretamente
`FacadeDependencies` e os serviços de aplicação usando os protocolos do domínio.
O contexto `async with Container(...)` fecha clientes e conexões que criou.
Adapters fornecidos pelo host continuam sob o ciclo de vida do host.

Os pipelines registrados são `corrective_rag`, `simple_rag`,
`react_agent_native` e `react_agent_structured_json`. A indexação substitui o
snapshot completo de cada fonte em uma transação, inclusive quando o documento
encolhe ou fica vazio. Fontes são identificadas por `source_type` e `source_id`.
Cada aplicação deve configurar seu próprio banco ou um retriever com o escopo
correto; isolamento entre tenants não é aplicado automaticamente.

O adaptador PostgreSQL atual usa vetores de **1024 dimensões**. Outros modelos
de embeddings precisam ser compatíveis com essa dimensão ou receber outro
adaptador/schema. API FastAPI e função de worker são interfaces opcionais;
o host configura autenticação, broker e execução das tarefas.

## Geração de drafts scrap e revisão humana

O módulo pronto para acoplamento recebe snapshots imutáveis do host em
`ReviewRequest` ou `ReportRequest`. Cada evidência carrega organização,
identidade da fonte, versão e escopo de acesso. O host deve autorizar as fontes
antes de montar esses objetos. Dossiers de relatório só recuperam ocorrências
selecionadas e métricas enviadas no próprio pedido; uma revisão individual pode
consultar revisões aprovadas semelhantes, sempre identificadas como hipótese.

```python
async with Container(Settings()) as container:
    assistant = container.build_scrap_assistant()
    draft = await assistant.draft_report(report_request)
    # Validar a versão atual no host antes de aplicar qualquer payload.
```

`packs.scrap.host_mapping` converte um draft aprovado em comandos compatíveis
com `ScrapReviewWrite`, `ReportUpdate` e `ReportSectionsUpdate`. A camada de
integração do Hanaro ainda precisa autenticar o analista, buscar snapshots com
escopo de tenant, persistir os jobs, apresentar a fila e aplicar as mutações com
controle otimista de versão. Os mapeadores preservam campos não sugeridos e
recusam drafts incompletos ou versões desatualizadas. O SQLite e a CLI incluídos
são adaptadores locais para desenvolvimento e avaliação; implemente os mesmos
limites com os repositórios, fila e interface do host em produção.
