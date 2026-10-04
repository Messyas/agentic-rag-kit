"""Local OpenAI-compatible inference adapter for LM Studio gateways."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from rag_kit.domain.errors import LLMPermanentError, LLMTransientError
from rag_kit.domain.ports.llm import LLMRequest, LLMResponse, LLMUsage, ToolInvocation


class OpenAICompatClient:
    def __init__(self, base_url: str) -> None:
        self.health_url = base_url.rstrip("/").removesuffix("/v1")
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [message.model_dump(exclude_none=True) for message in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.seed is not None:
            body["seed"] = request.seed
        if request.json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": request.json_schema, "strict": True},
            }
        if request.tools:
            body["tools"] = [
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
        try:
            response = await self._client.post(
                "chat/completions", json=body, timeout=request.timeout_s
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            if error.response.status_code >= 500 or error.response.status_code == 429:  # noqa: PLR2004 - HTTP status constants
                raise LLMTransientError("local gateway server error") from error  # noqa: TRY003 - contextual domain error
            raise LLMPermanentError("local gateway rejected request") from error  # noqa: TRY003 - contextual domain error
        except httpx.HTTPError as error:
            raise LLMTransientError("local gateway unavailable") from error  # noqa: TRY003 - contextual domain error
        payload = response.json()
        message = payload["choices"][0]["message"]
        calls = [
            ToolInvocation(
                id=item.get("id") or str(uuid.uuid4()),
                name=item["function"]["name"],
                arguments=json.loads(item["function"]["arguments"]),
            )
            for item in message.get("tool_calls", [])
        ]
        usage = payload.get("usage", {})
        return LLMResponse(
            content=message.get("content") or "",
            model=payload.get("model", request.model),
            tool_calls=calls,
            usage=LLMUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            ),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
