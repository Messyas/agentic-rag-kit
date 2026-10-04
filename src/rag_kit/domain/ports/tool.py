"""Typed tools used by the investigation agent."""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from rag_kit.domain.ports.llm import ToolSpec


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    content: str
    data: dict[str, Any]
    source_ids: tuple[str, ...] = ()
    trusted_numbers: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...
    @property
    def args_model(self) -> type[BaseModel]: ...
    async def run(self, arguments: BaseModel) -> ToolResult: ...
