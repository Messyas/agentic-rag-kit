"""Concrete adapter composition confined to the bootstrap layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_kit.infrastructure.llm.balancer.router import BalancedLLMClient, BalancerPolicy
from rag_kit.infrastructure.llm.balancer.strategies import LeastBusy, LowestLatency, RoundRobin
from rag_kit.infrastructure.llm.decorators.bulkhead import BulkheadLLM
from rag_kit.infrastructure.llm.decorators.cache import CachingLLM
from rag_kit.infrastructure.llm.decorators.circuit_breaker import (
    CircuitBreakerLLM,
    CircuitBreakerPolicy,
)
from rag_kit.infrastructure.llm.decorators.retry import RetryingLLM, RetryPolicy
from rag_kit.infrastructure.llm.decorators.tracing import TracingLLM
from rag_kit.infrastructure.llm.ollama_client import OllamaClient, OllamaConnection
from rag_kit.infrastructure.llm.openai_compat_client import OpenAICompatClient

if TYPE_CHECKING:
    from rag_kit.bootstrap.settings import Settings
    from rag_kit.domain.ports.llm import LLMClient
    from rag_kit.domain.ports.tracer import Tracer


def build_llm_client(settings: Settings, tracer: Tracer) -> LLMClient:
    balancer = settings.llm.balancer
    if balancer and balancer.backends:
        clients = {backend.name: _backend(settings, backend.url) for backend in balancer.backends}
        strategy = {
            "round_robin": RoundRobin(),
            "least_busy": LeastBusy(),
            "latency": LowestLatency(),
        }[balancer.strategy]
        client: LLMClient = BalancedLLMClient(
            clients,
            strategy,
            BalancerPolicy(
                balancer.cooldown_s, balancer.max_failovers, settings.llm.max_concurrent
            ),
        )
    else:
        client = _backend(
            settings,
            settings.ollama.host if settings.llm.provider == "ollama" else settings.llm.base_url,
        )
    client = RetryingLLM(client, RetryPolicy(settings.llm.retries))
    client = CircuitBreakerLLM(
        client, CircuitBreakerPolicy(settings.llm.breaker_failures, settings.llm.breaker_reset_s)
    )
    client = BulkheadLLM(client, settings.llm.max_concurrent)
    if settings.llm.cache_enabled:
        client = CachingLLM(client)
    return TracingLLM(client, tracer)


def _backend(settings: Settings, url: str) -> LLMClient:
    if settings.llm.provider == "ollama":
        return OllamaClient(OllamaConnection(host=url, keep_alive=settings.ollama.keep_alive))
    return OpenAICompatClient(url)
