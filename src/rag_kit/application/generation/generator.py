"""Schema-constrained generation with bounded validation repair."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from rag_kit.domain.errors import LLMOutputError
from rag_kit.domain.ports.llm import LLMClient, LLMRequest, LLMUsage, Message

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rag_kit.application.generation.prompt_builder import PromptBuilder
    from rag_kit.application.pack import PackSpec
    from rag_kit.domain.analysis import Subject
    from rag_kit.domain.models import ScoredChunk


@dataclass(frozen=True, slots=True)
class RunnerOptions:
    model: str
    max_repairs: int = 1
    context_tokens: int = 4096
    max_output_tokens: int = 1200

    def __post_init__(self) -> None:
        if self.max_repairs < 0:
            raise ValueError("max_repairs must be nonnegative")  # noqa: TRY003 - contextual domain error


@dataclass(frozen=True, slots=True)
class StructuredOutput:
    value: BaseModel
    usage: LLMUsage
    repairs_used: int


class StructuredOutputRunner:
    def __init__(self, llm: LLMClient, options: RunnerOptions) -> None:
        self._llm = llm
        self._options = options

    async def run(self, messages: Sequence[Message], schema: type[BaseModel]) -> StructuredOutput:
        conversation = list(messages)
        usage = LLMUsage()
        for repairs in range(self._options.max_repairs + 1):
            response = await self._llm.complete(
                LLMRequest(
                    model=self._options.model,
                    messages=conversation,
                    json_schema=schema.model_json_schema(),
                    num_ctx=self._options.context_tokens,
                    max_tokens=self._options.max_output_tokens,
                )
            )
            usage = sum_usage(usage, response.usage)
            try:
                value = schema.model_validate_json(response.content)
            except ValidationError as error:
                if repairs == self._options.max_repairs:
                    raise LLMOutputError("structured output failed validation") from error  # noqa: TRY003 - contextual domain error
                conversation.extend(
                    [
                        Message(role="assistant", content=response.content),
                        Message(
                            role="user",
                            content="Correct JSON: "
                            + str(error.errors(include_input=False, include_url=False)),
                        ),
                    ]
                )
            else:
                return StructuredOutput(value, usage, repairs)
        raise LLMOutputError("no generation attempts configured")  # noqa: TRY003 - contextual domain error


def sum_usage(total: LLMUsage, addition: LLMUsage) -> LLMUsage:
    return LLMUsage(
        prompt_tokens=total.prompt_tokens + addition.prompt_tokens,
        completion_tokens=total.completion_tokens + addition.completion_tokens,
        total_duration_s=total.total_duration_s + addition.total_duration_s,
    )


class StructuredGenerator:
    def __init__(
        self, builder: PromptBuilder, runner: StructuredOutputRunner, pack: PackSpec
    ) -> None:
        self._builder = builder
        self._runner = runner
        self._pack = pack

    async def generate(
        self,
        subject: Subject,
        evidence: Sequence[ScoredChunk],
        feedback: Sequence[Any] = (),
        trusted_numbers: Mapping[str, str] | None = None,
    ) -> StructuredOutput:
        numbers = {**(trusted_numbers or {}), **self._pack.trusted_numbers(subject)}
        messages = self._builder.build(subject, evidence, numbers, self._pack.output_model)
        if feedback:
            messages.append(Message(role="user", content=f"Repair guard violations: {feedback}"))
        return await self._runner.run(messages, self._pack.output_model)
