"""Workflow nodes sharing tracing and error translation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rag_kit.application.generation.generator import StructuredGenerator, sum_usage
from rag_kit.application.generation.output_guard import GuardChain, GuardContext
from rag_kit.domain.errors import NodeError, RagKitError

if TYPE_CHECKING:
    from rag_kit.application.pack import PackSpec
    from rag_kit.application.workflow.state import WorkflowState
    from rag_kit.domain.ports.grader import Grader
    from rag_kit.domain.ports.retriever import Retriever
    from rag_kit.domain.ports.tracer import Tracer


@dataclass(frozen=True, slots=True)
class RunContext:
    pack: PackSpec
    retriever: Retriever
    grader: Grader
    generator: StructuredGenerator
    guards: GuardChain
    tracer: Tracer


class Node(ABC):
    name: str

    async def execute(self, state: WorkflowState, context: RunContext) -> WorkflowState:
        with context.tracer.span(self.name, run_id=state.run_id) as span:
            try:
                result = await self.run(state, context)
                span.set("candidate_count", len(result.candidates))
                if result.grade is not None:
                    span.set("sufficient", result.grade.sufficient)
            except RagKitError:
                raise
            except Exception as error:
                raise NodeError(self.name, error) from error
            else:
                return result

    @abstractmethod
    async def run(self, state: WorkflowState, context: RunContext) -> WorkflowState: ...


class BuildQueryNode(Node):
    name = "build_query"

    async def run(self, state: WorkflowState, context: RunContext) -> WorkflowState:
        return state.model_copy(update={"query": context.pack.query_builder.build(state.subject)})


class RetrieveNode(Node):
    name = "retrieve"

    async def run(self, state: WorkflowState, context: RunContext) -> WorkflowState:
        if state.query is None:
            raise ValueError("retrieval requires a query")  # noqa: TRY003 - contextual domain error
        candidates = await context.retriever.retrieve(state.query)
        return state.model_copy(update={"candidates": tuple(candidates)})


class GradeNode(Node):
    name = "grade"

    async def run(self, state: WorkflowState, context: RunContext) -> WorkflowState:
        if state.query is None:
            raise ValueError("grading requires a query")  # noqa: TRY003 - contextual domain error
        grade = await context.grader.grade(state.query.text, state.candidates)
        usage = getattr(context.grader, "last_usage", None)
        return state.model_copy(
            update={
                "grade": grade,
                "usage": sum_usage(state.usage, usage) if usage is not None else state.usage,
            }
        )


class GenerateNode(Node):
    name = "generate"

    async def run(self, state: WorkflowState, context: RunContext) -> WorkflowState:
        output = await context.generator.generate(
            state.subject, state.candidates, state.violations, state.trusted_numbers
        )
        return state.model_copy(
            update={
                "generated": output.value,
                "usage": sum_usage(state.usage, output.usage),
                "repairs_used": state.repairs_used + output.repairs_used,
            }
        )


class ValidateNode(Node):
    name = "validate"

    async def run(self, state: WorkflowState, context: RunContext) -> WorkflowState:
        if state.generated is None:
            raise ValueError("validation requires generated output")  # noqa: TRY003 - contextual domain error
        guard_context = GuardContext(
            allowed_source_ids=frozenset(item.chunk.ref.source_id for item in state.candidates),
            trusted_numbers={
                **state.trusted_numbers,
                **context.pack.trusted_numbers(state.subject),
            },
        )
        violations = context.guards.run(state.generated, guard_context)
        return state.model_copy(update={"violations": tuple(violations)})
