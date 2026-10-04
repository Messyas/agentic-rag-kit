"""Ollama adapter translating client responses and failures to domain types."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx
import ollama

from rag_kit.domain.errors import LLMPermanentError, LLMTimeoutError, LLMTransientError
from rag_kit.domain.ports.llm import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ToolInvocation,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

HTTP_SERVER_ERROR = 500
NANOSECONDS_PER_SECOND = 1_000_000_000


class _AsyncChatClient(Protocol):
    async def chat(  # noqa: PLR0913 - mirrors the Ollama SDK call signature
        self,
        *,
        model: str,
        messages: Sequence[dict[str, Any]],
        options: dict[str, Any],
        keep_alive: str,
        format: dict[str, Any] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> ollama.ChatResponse: ...

    def close(self) -> Awaitable[None]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaConnection:
    host: str
    keep_alive: str = "10m"
    backend_id: str = "ollama-local"


class OllamaClient(LLMClient):
    def __init__(
        self, connection: OllamaConnection, client: ollama.AsyncClient | None = None
    ) -> None:
        self._connection = connection
        ollama_client = client or ollama.AsyncClient(host=connection.host)
        self._client = cast("_AsyncChatClient", ollama_client)

    @property
    def health_url(self) -> str:
        return self._connection.host

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            chat_call = self._client.chat(**self._arguments(request))
            response = await asyncio.wait_for(chat_call, timeout=request.timeout_s)
        except TimeoutError as exc:
            raise LLMTimeoutError("Ollama request timed out") from exc  # noqa: TRY003
        except ollama.ResponseError as exc:
            if exc.status_code >= HTTP_SERVER_ERROR or exc.status_code == 0:
                raise LLMTransientError("Ollama server error") from exc  # noqa: TRY003
            raise LLMPermanentError("Ollama rejected the request") from exc  # noqa: TRY003
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise LLMTransientError("Ollama is unavailable") from exc  # noqa: TRY003
        return self._response(response, request.model)

    def _arguments(self, request: LLMRequest) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": request.temperature}
        if request.seed is not None:
            options["seed"] = request.seed
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if request.num_ctx is not None:
            options["num_ctx"] = request.num_ctx
        arguments: dict[str, Any] = {
            "model": request.model,
            "messages": [message.model_dump(exclude_none=True) for message in request.messages],
            "options": options,
            "keep_alive": self._connection.keep_alive,
        }
        if request.json_schema is not None:
            arguments["format"] = request.json_schema
        if request.tools:
            arguments["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                }
                for tool in request.tools
            ]
        return arguments

    def _response(self, response: Any, model: str) -> LLMResponse:
        message: Any = response.message
        tool_calls: list[Any] = list(message.tool_calls or [])
        calls = [
            ToolInvocation(
                id=getattr(call, "id", None) or str(uuid.uuid4()),
                name=call.function.name,
                arguments=dict(call.function.arguments),
            )
            for call in tool_calls
        ]
        eval_duration = getattr(response, "eval_duration", 0) or 0
        completion_tokens = getattr(response, "eval_count", 0) or 0
        usage = LLMUsage(
            prompt_tokens=getattr(response, "prompt_eval_count", 0) or 0,
            completion_tokens=completion_tokens,
            total_duration_s=(getattr(response, "total_duration", 0) or 0) / NANOSECONDS_PER_SECOND,
            tokens_per_second=(completion_tokens * NANOSECONDS_PER_SECOND / eval_duration)
            if eval_duration
            else None,
        )
        return LLMResponse(
            content=message.content or "",
            tool_calls=calls,
            usage=usage,
            model=getattr(response, "model", None) or model,
            backend_id=self._connection.backend_id,
        )

    async def aclose(self) -> None:
        await self._client.close()
