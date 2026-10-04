"""Interchangeable native and structured JSON tool-call selection."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from rag_kit.application.generation.generator import (
    RunnerOptions,
    StructuredOutputRunner,
    sum_usage,
)
from rag_kit.domain.ports.llm import (
    LLMClient,
    LLMRequest,
    LLMUsage,
    Message,
    ToolInvocation,
    ToolSpec,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


class ToolCallingStrategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def usage(self) -> LLMUsage: ...

    async def choose(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> list[ToolInvocation]: ...


class NativeToolCalling:
    name = "native"

    def __init__(self, llm: LLMClient, model: str, system_prompt: str = "") -> None:
        self._llm = llm
        self._model = model
        self._prompt = system_prompt
        self._usage = LLMUsage()

    @property
    def usage(self) -> LLMUsage:
        return self._usage

    async def choose(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> list[ToolInvocation]:
        response = await self._llm.complete(
            LLMRequest(
                model=self._model,
                messages=[Message(role="system", content=self._prompt), *messages],
                tools=list(tools),
            )
        )
        self._usage = sum_usage(self._usage, response.usage)
        return response.tool_calls


class SelectedTool(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolDecision(BaseModel):
    calls: list[SelectedTool] = Field(default_factory=list[SelectedTool])


class StructuredToolCalling:
    name = "structured_json"

    def __init__(self, llm: LLMClient, model: str, system_prompt: str = "") -> None:
        self._runner = StructuredOutputRunner(llm, RunnerOptions(model))
        self._prompt = system_prompt
        self._usage = LLMUsage()

    @property
    def usage(self) -> LLMUsage:
        return self._usage

    async def choose(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> list[ToolInvocation]:
        descriptions = Message(
            role="system",
            content=self._prompt
            + "\nChoose calls from these tools, or return calls=[] to stop: "
            + str([tool.model_dump() for tool in tools]),
        )
        output = await self._runner.run([*messages, descriptions], ToolDecision)
        self._usage = sum_usage(self._usage, output.usage)
        decision = ToolDecision.model_validate(output.value)
        return [
            ToolInvocation(id=str(uuid.uuid4()), name=call.name, arguments=call.arguments)
            for call in decision.calls
        ]
