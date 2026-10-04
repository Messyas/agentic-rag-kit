"""Typed asynchronous language-model boundary."""

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

Priority = Literal["high", "normal", "low"]


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters_schema: dict[str, Any]


class ToolInvocation(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.0
    seed: int | None = 42
    max_tokens: int | None = None
    num_ctx: int | None = None
    json_schema: dict[str, Any] | None = None
    tools: list[ToolSpec] | None = None
    priority: Priority = "normal"
    timeout_s: float = 120.0
    tags: dict[str, str] = Field(default_factory=dict)


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_duration_s: float = 0.0
    tokens_per_second: float | None = None


class LLMResponse(BaseModel):
    content: str
    tool_calls: list[ToolInvocation] = []
    usage: LLMUsage = Field(default_factory=LLMUsage)
    model: str
    backend_id: str | None = None


@runtime_checkable
class LLMClient(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
    async def aclose(self) -> None: ...
