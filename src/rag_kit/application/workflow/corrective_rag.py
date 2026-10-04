"""Bounded corrective RAG pipeline with deterministic abstention."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from rag_kit.application.generation.generator import sum_usage
from rag_kit.application.workflow.nodes import (
    BuildQueryNode,
    GenerateNode,
    GradeNode,
    RetrieveNode,
    RunContext,
    ValidateNode,
)
from rag_kit.application.workflow.policies import WorkflowPolicy
from rag_kit.application.workflow.state import WorkflowState
from rag_kit.domain.analysis import AnalysisOutcome, AnalysisResult, Gap, Subject
from rag_kit.domain.errors import LLMOutputError

if TYPE_CHECKING:
    from rag_kit.application.generation.output_guard import ClaimsProvider
    from rag_kit.application.workflow.corrections import CorrectionPlanner


@dataclass(frozen=True, slots=True)
class PipelineIdentity:
    name: str = "corrective_rag"
    version: str = "1"


class CorrectiveRagPipeline:
    def __init__(
        self,
        context: RunContext,
        planner: CorrectionPlanner,
        policy: WorkflowPolicy | None = None,
        identity: PipelineIdentity | None = None,
    ) -> None:
        self._context = context
        self._planner = planner
        self._policy = policy or WorkflowPolicy()
        self._identity = identity or PipelineIdentity()

    @property
    def name(self) -> str:
        return self._identity.name

    @property
    def version(self) -> str:
        return self._identity.version

    async def analyze(self, subject: Subject) -> AnalysisResult:
        state = WorkflowState(subject=subject, run_id=str(uuid.uuid4()))
        state = await BuildQueryNode().execute(state, self._context)
        state = await self._retrieve_and_grade(state)
        while (
            state.grade
            and not state.grade.sufficient
            and state.corrections_used < self._policy.max_corrections
        ):
            if state.query is None:
                break
            query = await self._planner.next_query(state.query, state.corrections_used)
            if query is None:
                break
            state = state.model_copy(
                update={
                    "query": query,
                    "corrections_used": state.corrections_used + 1,
                    "usage": sum_usage(state.usage, self._planner.last_usage),
                }
            )
            state = await self._retrieve_and_grade(state)
        if not state.grade or not state.grade.sufficient:
            return self._finalize(state)
        relevant = set(state.grade.relevant_chunks)
        state = state.model_copy(
            update={
                "candidates": tuple(
                    item for item in state.candidates if item.chunk.chunk_id in relevant
                )
            }
        )
        return await self.compose(state)

    async def _retrieve_and_grade(self, state: WorkflowState) -> WorkflowState:
        state = await RetrieveNode().execute(state, self._context)
        return await GradeNode().execute(state, self._context)

    async def compose(self, state: WorkflowState) -> AnalysisResult:
        if not state.candidates:
            return self._finalize(state)
        try:
            for attempt in range(self._policy.max_guard_repairs + 1):
                if attempt:
                    state = state.model_copy(update={"repairs_used": state.repairs_used + 1})
                state = await GenerateNode().execute(state, self._context)
                state = await ValidateNode().execute(state, self._context)
                if not state.violations:
                    break
        except LLMOutputError:
            state = state.model_copy(update={"generated": None})
        return self._finalize(state)

    def abstain(self, state: WorkflowState) -> AnalysisResult:
        return self._finalize(state.model_copy(update={"generated": None}))

    def _finalize(self, state: WorkflowState) -> AnalysisResult:
        facts = self._context.pack.deterministic_facts(state.subject)
        if state.generated is None or state.violations:
            return AnalysisResult(
                subject_id=state.subject.subject_id,
                outcome=AnalysisOutcome.INSUFFICIENT_EVIDENCE,
                claims=tuple(facts),
                gaps=(
                    Gap(
                        question="Quais evidências revisadas sustentam a análise desta ocorrência?"
                    ),
                ),
                payload={
                    "observed_facts": [fact.model_dump() for fact in facts],
                    "observed_fields": state.subject.fields,
                },
                violations=state.violations,
                run_id=state.run_id,
                usage={**state.usage.model_dump(), "repairs_used": state.repairs_used},
                source_refs=tuple(dict.fromkeys(item.chunk.ref for item in state.candidates)),
            )
        payload = state.generated.model_dump(mode="json")
        claims = list(cast("ClaimsProvider", state.generated).claims())
        gaps = tuple(Gap.model_validate(item) for item in payload.get("gaps", []))
        return AnalysisResult(
            subject_id=state.subject.subject_id,
            outcome=AnalysisOutcome(payload["outcome"].upper()),
            claims=tuple(facts + claims),
            gaps=gaps,
            payload={
                **payload,
                "observed_facts": [fact.model_dump() for fact in facts],
                "observed_fields": state.subject.fields,
            },
            run_id=state.run_id,
            usage={**state.usage.model_dump(), "repairs_used": state.repairs_used},
            source_refs=tuple(dict.fromkeys(item.chunk.ref for item in state.candidates)),
        )
