"""Routing policies for healthy local inference backends."""

from collections.abc import Sequence
from dataclasses import dataclass

from rag_kit.domain.errors import LLMTransientError


@dataclass(slots=True)
class BackendState:
    name: str
    busy: int = 0
    latency_s: float = 0.0
    cooldown_until: float = 0.0
    healthy: bool = True


class RoundRobin:
    def __init__(self) -> None:
        self._cursor = 0

    def select(self, states: Sequence[BackendState]) -> BackendState:
        if not states:
            raise LLMTransientError("no healthy inference backends")  # noqa: TRY003 - contextual domain error
        state = states[self._cursor % len(states)]
        self._cursor += 1
        return state


class LeastBusy:
    def select(self, states: Sequence[BackendState]) -> BackendState:
        if not states:
            raise LLMTransientError("no healthy inference backends")  # noqa: TRY003 - contextual domain error
        return min(states, key=lambda state: state.busy)


class LowestLatency:
    def select(self, states: Sequence[BackendState]) -> BackendState:
        if not states:
            raise LLMTransientError("no healthy inference backends")  # noqa: TRY003 - contextual domain error
        return min(states, key=lambda state: state.latency_s)
