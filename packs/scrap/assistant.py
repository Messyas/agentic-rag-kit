"""Source-grounded scrap draft composition using the kit's local LLM port."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from packs.scrap.assistant_schemas import (
    AssistantDraft,
    BaseRequest,
    DraftSuggestion,
    Evidence,
    FourM,
    FourMItem,
    ReportRequest,
    ReviewRequest,
    SupportedStatement,
)
from pydantic import Field

from rag_kit.application.generation.generator import RunnerOptions, StructuredOutputRunner
from rag_kit.domain.models import Frozen
from rag_kit.domain.ports.llm import Message

if TYPE_CHECKING:
    from rag_kit.domain.ports.llm import LLMClient

_FAMILIES: tuple[FourM, ...] = ("MAN", "MACHINE", "METHOD", "MATERIAL")
_STOPWORDS = frozenset({"para", "como", "com", "uma", "das", "dos", "que", "por", "scrap"})
_SOURCE_LIMIT = 12
_TEXT_LIMIT = 750
_MIN_TOKEN_LENGTH = 3
_MIN_OBSERVATION_LENGTH = 5
_MIN_SIMILARITY_TERMS = 2


class ModelHypothesis(Frozen):
    family: FourM
    statement: str = Field(min_length=5, max_length=300)
    source_id: str
    quote: str = Field(min_length=3, max_length=500)
    next_check: str = Field(min_length=5, max_length=200)


class ModelAnalysis(Frozen):
    context: tuple[SupportedStatement, ...] = ()
    hypotheses: tuple[ModelHypothesis, ...] = ()
    gaps: tuple[str, ...] = ()


def snapshot_fingerprint(request: BaseRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"request_id"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\w+", value.casefold())
        if len(token) >= _MIN_TOKEN_LENGTH and token not in _STOPWORDS
    }


def _comment_terms(sources: tuple[Evidence, ...]) -> set[str]:
    comments: list[str] = []
    for source in sources:
        if source.source_type != "occurrence":
            continue
        marker = "requisition_comment: "
        if marker in source.text:
            comments.append(source.text.split(marker, 1)[1].splitlines()[0])
    return _tokens(" ".join(comments))


def _rank_sources(request: ReviewRequest | ReportRequest, query: str) -> tuple[Evidence, ...]:
    terms = _tokens(query)
    scored: list[tuple[int, Evidence]] = []
    for source in request.sources:
        overlap = len(terms & _tokens(source.text))
        selected = isinstance(request, ReportRequest) and (
            source.occurrence_id in request.selected_occurrence_ids
            or source.source_type == "metric"
        )
        same_case = isinstance(request, ReviewRequest) and (
            source.occurrence_id == request.occurrence_id
        )
        # Report dossiers must remain closed over the selected occurrences.
        # Similarity retrieval is useful for a single review, where prior
        # reviewed cases may be surfaced explicitly as hypotheses.
        eligible = selected or same_case or (isinstance(request, ReviewRequest) and overlap > 0)
        if eligible:
            scored.append((overlap + (100 if selected or same_case else 0), source))
    scored.sort(key=lambda pair: (-pair[0], pair[1].source_id))
    return tuple(source for _, source in scored[:_SOURCE_LIMIT])


def _trusted_claims(
    analysis: ModelAnalysis,
    evidence: tuple[Evidence, ...],
    request: ReviewRequest | ReportRequest,
) -> tuple[tuple[SupportedStatement, ...], tuple[ModelHypothesis, ...], tuple[str, ...]]:
    sources = {source.source_id: source for source in evidence}
    issues: list[str] = []
    comment_terms = _comment_terms(evidence)
    selected = (
        {request.occurrence_id}
        if isinstance(request, ReviewRequest)
        else set(request.selected_occurrence_ids)
    )

    def supported(source_id: str, quote: str, statement: str) -> bool:
        source = sources.get(source_id)
        if source is None:
            return False
        other_review = source.source_type == "scrap_review" and source.occurrence_id not in selected
        similarity_label = any(
            phrase in statement.casefold()
            for phrase in ("caso semelhante", "caso similar", "outra ocorrência")
        )
        return bool(
            quote.casefold() in source.text.casefold()
            and not re.search(r"\d", statement)
            and (
                not other_review
                or (
                    similarity_label
                    and len(comment_terms & _tokens(source.text)) >= _MIN_SIMILARITY_TERMS
                )
            )
        )

    claims = tuple(
        claim
        for claim in analysis.context
        if supported(claim.source_id, claim.quote, claim.statement)
    )
    hypotheses = tuple(
        item
        for item in analysis.hypotheses
        if supported(item.source_id, item.quote, item.statement)
    )
    rejected = len(analysis.context) + len(analysis.hypotheses) - len(claims) - len(hypotheses)
    if rejected:
        issues.append(
            f"{rejected} afirmação(ões) descartada(s) por falta de citação válida ou número livre"
        )
    return claims, hypotheses, tuple(issues)


def _observed_claims(sources: tuple[Evidence, ...]) -> tuple[SupportedStatement, ...]:
    """Compose literal item and comment facts without relying on model recall."""
    claims: list[SupportedStatement] = []
    for source in sources:
        if source.source_type != "occurrence":
            continue
        for label, field in (
            ("Item registrado", "item_description"),
            ("Observação de origem", "requisition_comment"),
        ):
            marker = f"{field}: "
            if marker not in source.text:
                continue
            value = source.text.split(marker, 1)[1].splitlines()[0].strip()
            if (
                len(value) < _MIN_OBSERVATION_LENGTH
                or value.casefold() == "scrap"
                or re.search(r"\d", value)
            ):
                continue
            claims.append(
                SupportedStatement(
                    statement=f"{label}: {value}", source_id=source.source_id, quote=value
                )
            )
    return tuple(claims)


def _similar_hypotheses(sources: tuple[Evidence, ...]) -> tuple[ModelHypothesis, ...]:
    terms = _comment_terms(sources)
    labels: dict[FourM, str] = {
        "MAN": "mão de obra",
        "MACHINE": "máquina",
        "METHOD": "método",
        "MATERIAL": "material",
    }
    hypotheses: list[ModelHypothesis] = []
    for source in sources:
        family = source.metadata.get("cause_family")
        if (
            source.source_type != "scrap_review"
            or family not in labels
            or len(terms & _tokens(source.text)) < _MIN_SIMILARITY_TERMS
            or any(item.family == family for item in hypotheses)
        ):
            continue
        hypotheses.append(
            ModelHypothesis(
                family=family,
                statement=(
                    f"Caso semelhante sugere verificar possível causa ligada a {labels[family]}."
                ),
                source_id=source.source_id,
                quote=source.text.splitlines()[-1][:500],
                next_check="Conferir evidência do caso atual com o analista.",
            )
        )
    return tuple(hypotheses)


def _four_m(
    hypotheses: tuple[ModelHypothesis, ...],
    request: ReviewRequest | ReportRequest,
    sources: tuple[Evidence, ...],
) -> tuple[FourMItem, ...]:
    items: list[FourMItem] = []
    by_id = {source.source_id: source for source in sources}
    selected = (
        {request.occurrence_id}
        if isinstance(request, ReviewRequest)
        else set(request.selected_occurrence_ids)
    )
    for family in _FAMILIES:
        matches = [item for item in hypotheses if item.family == family]
        first = matches[0] if matches else None
        origin = by_id.get(first.source_id) if first else None
        similar = (
            origin is not None
            and origin.source_type == "scrap_review"
            and origin.occurrence_id not in selected
        )
        items.append(
            FourMItem(
                family=family,
                observation=(f"Caso semelhante: {first.quote}" if similar else first.quote)
                if first
                else "",
                hypothesis=first.statement if first else "",
                certainty="HYPOTHESIS" if first else "UNASSESSED",
                source_ids=tuple(dict.fromkeys(item.source_id for item in matches)),
                next_check=first.next_check if first else "Verificar evidências com o analista.",
            )
        )
    return tuple(items)


def _deterministic_title(request: ReviewRequest | ReportRequest) -> str:
    if isinstance(request, ReportRequest):
        return request.title or f"Relatório de scrap {request.report_id}"
    item = str(request.occurrence.get("item_description") or "").strip()
    return (f"Análise de scrap: {item}" if item else "Análise de ocorrência de scrap")[:120]


def _suggestions(
    request: ReviewRequest | ReportRequest,
    claims: tuple[SupportedStatement, ...],
    four_m: tuple[FourMItem, ...],
) -> tuple[DraftSuggestion, ...]:
    title = _deterministic_title(request)
    narrative = " ".join(claim.statement for claim in claims)
    refs = tuple(dict.fromkeys(claim.source_id for claim in claims))
    suggestions = [DraftSuggestion(field="title", text=title)]
    if isinstance(request, ReviewRequest):
        if narrative:
            suggestions.append(
                DraftSuggestion(field="description", text=narrative[:800], source_ids=refs)
            )
        first = next((item for item in four_m if item.hypothesis), None)
        if first:
            suggestions.append(
                DraftSuggestion(
                    field="cause_family", text=first.family, source_ids=first.source_ids
                )
            )
            suggestions.append(
                DraftSuggestion(
                    field="cause_description", text=first.hypothesis, source_ids=first.source_ids
                )
            )
    else:
        suggestions.append(
            DraftSuggestion(
                field="objective", text="Analisar ocorrências de scrap e suas evidências."
            )
        )
        metric_sentences = tuple(
            f"{metric.key}: {metric.value} {metric.unit}." for metric in request.metrics
        )
        metric_refs = tuple(metric.source_id for metric in request.metrics)
        summary = " ".join((narrative, *metric_sentences)).strip()
        if narrative:
            suggestions.append(
                DraftSuggestion(field="CONTEXT", text=narrative[:10_000], source_ids=refs)
            )
        if summary:
            suggestions.append(
                DraftSuggestion(
                    field="executive_summary",
                    text=summary[:20_000],
                    source_ids=tuple(dict.fromkeys((*refs, *metric_refs))),
                )
            )
        causal = " ".join(item.hypothesis for item in four_m if item.hypothesis)
        causal_sources = tuple(
            dict.fromkeys(source_id for item in four_m for source_id in item.source_ids)
        )
        if causal:
            suggestions.append(
                DraftSuggestion(
                    field="CONCLUSIONS", text=causal[:10_000], source_ids=causal_sources
                )
            )
        for metric in request.metrics:
            suggestions.append(
                DraftSuggestion(
                    field=f"metric:{metric.key}",
                    text=f"{metric.value} {metric.unit}",
                    source_ids=(metric.source_id,),
                )
            )
    return tuple(suggestions)


class ScrapAssistantFacade:
    """Generate reviewable drafts from a host-authorized immutable snapshot."""

    def __init__(self, llm: LLMClient, model: str) -> None:
        self._runner = StructuredOutputRunner(llm, RunnerOptions(model, max_output_tokens=1400))
        self._model = model
        self._prompt_path = Path(__file__).parent / "prompts" / "draft.v1.jinja"
        self._prompt = self._prompt_path.read_text(encoding="utf-8")
        self._prompt_digest = hashlib.sha256(self._prompt.encode()).hexdigest()

    def generation_fingerprint(self, request: BaseRequest) -> str:
        """Bind idempotency to the source snapshot and generation configuration."""
        payload = {
            "snapshot": snapshot_fingerprint(request),
            "model": self._model,
            "prompt": self._prompt_digest,
            "schema": AssistantDraft.model_json_schema(),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    async def suggest_review(self, request: ReviewRequest) -> AssistantDraft:
        return await self._draft(request, "review")

    async def draft_report(self, request: ReportRequest) -> AssistantDraft:
        return await self._draft(request, "report")

    async def _draft(
        self, request: ReviewRequest | ReportRequest, kind: Literal["review", "report"]
    ) -> AssistantDraft:
        if isinstance(request, ReviewRequest):
            query = json.dumps(request.occurrence, ensure_ascii=False, default=str)
        else:
            observed = " ".join(
                source.text[:_TEXT_LIMIT]
                for source in request.sources
                if source.occurrence_id in request.selected_occurrence_ids
            )
            query = f"{request.title} {request.description} {observed}"
        sources = _rank_sources(request, query)
        fingerprint = snapshot_fingerprint(request)
        if not sources:
            return self._result(
                request, fingerprint, (), ModelAnalysis(), issues=("Sem fontes elegíveis.",)
            )
        source_data = [
            {
                "source_id": source.source_id,
                "source_type": source.source_type,
                "occurrence_id": source.occurrence_id,
                "cause_family": source.metadata.get("cause_family"),
                "text": source.text[:_TEXT_LIMIT],
            }
            for source in sources
        ]
        payload = {"kind": kind, "subject": query[:1200], "sources": source_data}
        output = await self._runner.run(
            [
                Message(role="system", content=self._prompt),
                Message(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            ModelAnalysis,
        )
        analysis = ModelAnalysis.model_validate(output.value)
        generated_claims, hypotheses, issues = _trusted_claims(analysis, sources, request)
        if not hypotheses:
            hypotheses = _similar_hypotheses(sources)
        claims = tuple(dict.fromkeys((*_observed_claims(sources), *generated_claims)))
        return self._result(
            request,
            fingerprint,
            sources,
            analysis,
            claims=claims,
            hypotheses=hypotheses,
            issues=issues,
            usage=output.usage.model_dump(mode="json"),
        )

    def _result(  # noqa: PLR0913 - explicit immutable draft components
        self,
        request: ReviewRequest | ReportRequest,
        fingerprint: str,
        sources: tuple[Evidence, ...],
        analysis: ModelAnalysis,
        *,
        claims: tuple[SupportedStatement, ...] = (),
        hypotheses: tuple[ModelHypothesis, ...] = (),
        issues: tuple[str, ...] = (),
        usage: dict[str, object] | None = None,
    ) -> AssistantDraft:
        four_m = _four_m(hypotheses, request, sources)
        gaps = (*analysis.gaps, *issues)
        if not hypotheses:
            gaps = (*gaps, "Causa 4M ainda não sustentada; revisar com o analista.")
        if not claims and not hypotheses:
            gaps = (*gaps, "Revisar fontes e registrar a análise humana antes de concluir.")
        return AssistantDraft(
            request_id=request.request_id,
            subject_id=request.occurrence_id
            if isinstance(request, ReviewRequest)
            else request.report_id,
            expected_version=request.expected_version,
            snapshot_fingerprint=fingerprint,
            outcome="COMPLETE" if claims and hypotheses else "INSUFFICIENT_EVIDENCE",
            suggestions=_suggestions(request, claims, four_m),
            claims=claims,
            four_m=four_m,
            gaps=tuple(dict.fromkeys(gaps)),
            source_refs=tuple(
                f"{source.source_type}:{source.source_id}@{source.version}" for source in sources
            ),
            run_metadata={
                "model": self._model,
                "pipeline": "bounded_rag",
                "prompt_version": "draft.v1",
                "prompt_sha256": self._prompt_digest,
                "usage": usage or {},
            },
        )
