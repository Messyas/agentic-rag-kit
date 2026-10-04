"""Focused contract checks for the Ollama adapter boundary."""

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from rag_kit.domain.errors import LLMTimeoutError
from rag_kit.domain.ports.llm import LLMRequest, Message
from rag_kit.infrastructure.llm.ollama_client import OllamaClient, OllamaConnection

if TYPE_CHECKING:
    import ollama


class StubOllamaClient:
    def __init__(self, response: Any = None) -> None:
        self.response = response

    async def chat(self, **_: Any) -> Any:
        return self.response

    async def close(self) -> None:
        return None


def _response() -> Any:
    return SimpleNamespace(
        message=SimpleNamespace(content="ok", tool_calls=[]),
        model="qwen2.5",
        prompt_eval_count=3,
        eval_count=2,
        total_duration=2_000_000_000,
        eval_duration=1_000_000_000,
    )


@pytest.mark.asyncio
async def test_ollama_client_maps_text_and_token_usage() -> None:
    fake = StubOllamaClient(_response())
    client = OllamaClient(
        OllamaConnection(host="http://localhost"), cast("ollama.AsyncClient", fake)
    )
    request = LLMRequest(model="qwen2.5", messages=[Message(role="user", content="hello")])

    response = await client.complete(request)

    assert response.content == "ok"
    assert response.usage.prompt_tokens == 3
    assert response.usage.tokens_per_second == 2.0


@pytest.mark.asyncio
async def test_ollama_client_maps_timeout_to_domain_error() -> None:
    class SlowClient(StubOllamaClient):
        async def chat(self, **_: Any) -> Any:
            await asyncio.sleep(0.02)
            return _response()

    client = OllamaClient(
        OllamaConnection(host="http://localhost"), cast("ollama.AsyncClient", SlowClient())
    )
    request = LLMRequest(
        model="qwen2.5", messages=[Message(role="user", content="hello")], timeout_s=0.001
    )

    with pytest.raises(LLMTimeoutError):
        await client.complete(request)
