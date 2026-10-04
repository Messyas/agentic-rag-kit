"""Local backend router with cooldown and bounded transient failover."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from rag_kit.domain.errors import LLMTransientError
from rag_kit.infrastructure.llm.balancer.gate import PriorityGate
from rag_kit.infrastructure.llm.balancer.health import BackendHealthMonitor
from rag_kit.infrastructure.llm.balancer.strategies import BackendState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rag_kit.domain.ports.llm import LLMClient, LLMRequest, LLMResponse


class RoutingStrategy(Protocol):
    def select(self, states: Sequence[BackendState]) -> BackendState: ...


@dataclass(frozen=True, slots=True)
class BalancerPolicy:
    cooldown_s: float = 15.0
    max_failovers: int = 1
    capacity: int = 1


class BalancedLLMClient:
    def __init__(
        self,
        clients: Mapping[str, LLMClient],
        strategy: RoutingStrategy,
        policy: BalancerPolicy | None = None,
    ) -> None:
        self._clients = dict(clients)
        self._states = {name: BackendState(name) for name in clients}
        self._strategy = strategy
        self._policy = policy or BalancerPolicy()
        self._gate = PriorityGate(self._policy.capacity)
        self._health = BackendHealthMonitor(
            {name: cast("Any", client).health_url for name, client in self._clients.items()},
            lambda name, healthy: self._set_health(name, healthy=healthy),
            "ollama"
            if all(hasattr(client, "_connection") for client in clients.values())
            else "openai_compat",
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self._health.start()
        async with self._gate.slot(request.priority):
            return await self._route(request)

    async def _route(self, request: LLMRequest) -> LLMResponse:
        attempts = min(len(self._states), self._policy.max_failovers + 1)
        for attempt in range(attempts):
            eligible = [
                state
                for state in self._states.values()
                if state.healthy and state.cooldown_until <= time.monotonic()
            ]
            state = self._strategy.select(eligible)
            started = time.monotonic()
            state.busy += 1
            try:
                response = await self._clients[state.name].complete(request)
                return response.model_copy(update={"backend_id": state.name})
            except LLMTransientError:
                state.cooldown_until = time.monotonic() + self._policy.cooldown_s
                if attempt + 1 == attempts:
                    raise
            finally:
                state.busy -= 1
                state.latency_s = time.monotonic() - started
        raise LLMTransientError("no inference backends configured")  # noqa: TRY003 - contextual domain error

    def _set_health(self, name: str, *, healthy: bool) -> None:
        self._states[name].healthy = healthy

    async def aclose(self) -> None:
        await self._health.aclose()
        for client in self._clients.values():
            await client.aclose()
