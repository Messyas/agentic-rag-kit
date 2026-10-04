# Contributing

## 4A. Clean Code Charter (mandatory for every task)

> This charter is part of the definition of done. Tooling enforces what it can (ruff, pyright, import-linter, an
> architecture test); code review enforces the rest with the checklist in §4B.

### N — Naming (semantic, English, domain vocabulary)

| ID | Rule | Example |
|---|---|---|
| N1 | Names reveal **intent**; a reader should not need the body to know what it does | `select_sufficient_evidence()` not `process()` |
| N2 | Classes are **nouns**, functions are **verbs**, booleans are **predicates** (`is_`, `has_`, `can_`, `should_`) | `is_evidence_sufficient`, `has_open_circuit` |
| N3 | Banned vague words: `data`, `info`, `item`, `obj`, `tmp`, `val`, `manager`, `helper`, `util`, `common`, `handler` (unless it truly is an event handler) | `RetryPolicy`, not `RetryHelper` |
| N4 | Units and scale in the name when a number is not self-explanatory | `timeout_seconds`, `max_context_tokens`, `ewma_latency_seconds` |
| N5 | One concept = one word across the codebase. Use the glossary below; never mix synonyms | always `subject`, never `record`/`item` for the thing being analyzed |
| N6 | No abbreviations except universal ones (`id`, `url`, `llm`, `rrf`, `ttl`); no single-letter names outside tiny comprehensions | `candidate`, not `c` |
| N7 | Code is English. The Portuguese word *gabarito* is `ground_truth` in code | `ground_truth`, `expected_outcome` |

**Glossary (use these words consistently)**

| Term | Meaning |
|---|---|
| subject | the thing being analyzed (one scrap occurrence) |
| evidence / chunk | retrieved text supporting an analysis |
| source reference | pointer to where a chunk came from (`SourceRef`) |
| grade / sufficiency | judgement of evidence relevance / whether it is enough |
| correction | one bounded attempt to improve retrieval |
| claim / hypothesis / gap | a sourced statement / an unconfirmed possible cause / missing evidence |
| pipeline (arm) | an `AnalysisPipeline` strategy under evaluation |
| pack | domain plug-in (`scrap`) |

### F — Functions and parameters (the "no parameter soup" rules)

| ID | Rule | Enforcement |
|---|---|---|
| F1 | A function does **one thing** at **one level of abstraction**; if you need "and" to describe it, split it | review |
| F2 | Target **≤ 20 lines**; hard limits: ≤ 25 statements, ≤ 8 branches, cyclomatic complexity ≤ 8 | ruff `PLR0915`, `PLR0912`, `C901` |
| F3 | **At most 3 positional parameters** (excluding `self`/`cls`) and **at most 4 parameters in total**. More than that ⇒ introduce a **parameter object** | ruff `PLR0913` (configured), review |
| F4 | **No boolean flag parameters.** A flag means two behaviours: split into two functions, or use an enum / Strategy | ruff `FBT001/FBT002/FBT003` |
| F5 | **Return named objects, not tuples** (`ValidationOutcome(valid_rows, issues)`), except trivial 2-tuples used immediately | review |
| F6 | Command–query separation: a function either changes state or returns a value, not both (exception: `create_if_absent`-style idempotent operations, documented) | review |
| F7 | Prefer **early returns / guard clauses**; maximum **2 levels** of nesting | ruff `SIM`, `PLR`, review |
| F8 | No `**kwargs` pass-through to hide parameters; no mutable default arguments; no magic numbers (name them or move to settings) | ruff `B006`, `PLR2004` |

**Parameter-object recipes ("destructuring" done right in Python)**

```python
# BAD: parameter soup, two booleans, hidden defaults
async def search(
    text,
    k=8,
    filters=None,
    source_types=None,
    rerank=False,
    widen=False,
    candidate_multiplier=3,
    timeout=30.0,
    priority="normal",
): ...


# GOOD: one cohesive request object (immutable) + one options object, keyword-only construction
@dataclass(frozen=True, slots=True, kw_only=True)
class SearchOptions:
    candidate_multiplier: int = 3
    timeout_seconds: float = 30.0
    priority: Priority = "normal"


async def search(
    self, query: RetrievalQuery, options: SearchOptions | None = None
) -> list[ScoredChunk]:
    options = options or SearchOptions()
    ...


# GOOD: callers override only what they need
await retriever.search(query, SearchOptions(priority="low"))
```

```python
# BAD: boolean flag selects behaviour
def build_retriever(settings: Settings, rerank: bool) -> Retriever: ...


# GOOD: behaviour comes from configuration and composition (Strategy + Null Object), no flag at the call site
def build_retriever(settings: Settings) -> Retriever:
    base = RETRIEVERS.create(settings.retrieval.mode, settings)
    return RerankingRetriever(
        base, RERANKERS.create(settings.rerank.provider, settings)
    )  # NullReranker = no-op
```

```python
# BAD: positional tuple the caller must remember
def run(self, rows) -> tuple[list[int], list[RowIssue]]: ...


valid, issues = chain.run(rows)


# GOOD: named result, readable at the call site, extensible without breaking callers
@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    valid_row_indexes: tuple[int, ...]
    issues: tuple[RowIssue, ...]

    @property
    def valid_row_count(self) -> int:
        return len(self.valid_row_indexes)


outcome = chain.run(rows)
```

```python
# Destructuring of structured data: unpack what you need, by name
match decision:
    case AgentDecision(kind="final"):
        return compose_with(evidence)
    case AgentDecision(kind="tool_calls", tool_calls=[first, *_]):
        return await dispatch(first)

for rank, candidate in enumerate(candidates, start=1):  # tuple unpacking in loops is fine
    ...
chunk, score = hit.chunk, hit.score  # unpack only when it improves readability
```

**Parameter objects and named results to introduce (sketches in this backlog use plain arguments for brevity)**

| Where a sketch has many arguments | Introduce |
|---|---|
| `RetryingLLM(...)` | `RetryPolicy(max_attempts, initial_delay_seconds, max_delay_seconds)` |
| `CircuitBreakerLLM(...)` | `CircuitBreakerPolicy(failure_threshold, reset_after_seconds)` |
| `BalancedLLMClient(...)` | `BalancerOptions(cooldown_seconds, max_failovers, admission_gate, clock)` |
| `OllamaClient(...)` | `OllamaConnection(host, keep_alive, backend_id)` |
| `OllamaEmbedder(...)` | `EmbedderOptions(model, batch_size, max_concurrent_requests)` |
| `CrossEncoderReranker(...)` | `RerankerOptions(device, batch_size, use_half_precision, max_length_tokens)` |
| `HybridRetriever(...)`, `reciprocal_rank_fusion(...)` | `FusionOptions(rrf_k, weights, candidate_k, top_n)` |
| `StructuredOutputRunner(...)` | `RunnerOptions(model, context_tokens, max_repairs)` + return `StructuredOutput(value, usage)` |
| `ScoreGrader(...)` | `GradingPolicy(signal, bands: ScoreBands(high, low), min_relevant, required_metadata)` |
| `ReActAgentPipeline(...)` | `AgentDependencies(llm, registry, strategy, composer, prompts, tracer)` + `AgentSettings(model, budget, version)` |
| `AnalysisFacade(...)` | `FacadeDependencies(ingestion, pipelines, runs, events)` |
| `compile_filters(...)` returning a tuple | `CompiledFilters(sql_fragment, bind_parameters)` |
| `CorrectionPlanner.next_query(...)` returning a tuple | `CorrectionProposal(strategy_name, query)` |

### C — Classes and SOLID

| ID | Rule |
|---|---|
| C1 | **S**: one reason to change per class. If a class name needs "And"/"Manager", split it. |
| C2 | **O**: extend by adding a class and registering it; never by adding an `if kind == ...` branch to existing code. |
| C3 | **L**: every adapter passes the contract test of its port. A subclass that weakens a postcondition is a bug. |
| C4 | **I**: ports have a handful of methods. Readers and writers are separate. |
| C5 | **D**: constructors receive collaborators (as Protocols); nothing instantiates its own infrastructure; only `bootstrap/container.py` does. |
| C6 | Prefer **composition** (Decorator, Strategy) over inheritance. Inheritance only for Template Method (`Node`) and `LLMDecorator`. |
| C7 | Value objects are **immutable** (`frozen=True`); entities change through explicit transitions (`ProcessingState`). |
| C8 | **No primitive obsession**: use `NewType` for identifiers (`SubjectId`, `ChunkId`, `RunId`) and `StrEnum`/`Literal` for closed sets instead of raw strings. |

### D/E — Data, types and errors

| ID | Rule |
|---|---|
| E1 | Domain exceptions only (`domain/errors.py`); adapters translate library errors; **no bare `except`**, no `except Exception` except at documented boundaries (tool dispatch, event subscribers, batch loops) |
| E2 | Never swallow: log with context or re-raise. Never use `None`/`False` to signal an error that deserves an exception |
| E3 | Fail fast at boundaries (parse, validate, convert to domain objects immediately); the interior trusts its types |
| E4 | Full type annotations; pyright strict; no `Any` in domain/application except at JSON boundaries |

### S — Structure and readability

| ID | Rule |
|---|---|
| S1 | Read top-to-bottom like prose: public API first, helpers below, each helper named for what it *means* |
| S2 | Comments explain **why** (a constraint, a trade-off, a gotcha), never **what**; no commented-out code; docstrings are one line unless the contract is subtle |
| S3 | No clever one-liners; a comprehension is fine until you need to explain it |
| S4 | No dead code, no unused parameters, no `TODO` without an issue/backlog ID |
| S5 | A module is one cohesive idea, ≤ ~250 lines; names like `utils.py`, `helpers.py`, `common.py` are forbidden (architecture test) |

### T — Tests

| ID | Rule |
|---|---|
| T1 | Test names are sentences: `test_circuit_opens_after_threshold_failures`, `test_planner_never_repeats_a_strategy` |
| T2 | Arrange–Act–Assert with blank lines between; one behaviour per test |
| T3 | **Fakes over mocks**; assert on observable behaviour, not on call counts of internals (exception: "the LLM was not called") |
| T4 | No logic (loops/conditionals) in tests; use parametrization and builders (`a_subject(...)`, `a_chunk(...)`) |
| T5 | Every bug fix starts with a failing regression test |

### G — Git

Conventional Commits (`feat(retrieval): add RRF fusion`), one task per commit (or PR), commit only green states, evaluation results attached to any change to prompts, thresholds or models.

---

