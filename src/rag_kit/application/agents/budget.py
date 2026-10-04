"""Per-run investigation budgets and duplicate-call protection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rag_kit.domain.errors import BudgetExceeded

if TYPE_CHECKING:
    from rag_kit.domain.ports.llm import ToolInvocation


@dataclass(frozen=True, slots=True)
class AgentBudget:
    max_steps: int = 5
    max_tool_calls: int = 6
    timeout_s: float = 120.0
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        if (
            self.max_steps < 1
            or self.max_tool_calls < 0
            or self.timeout_s <= 0
            or self.max_tokens < 1
        ):
            raise ValueError("agent budgets require positive steps/time and nonnegative calls")  # noqa: TRY003


class BudgetTracker:
    def __init__(self, budget: AgentBudget) -> None:
        self._budget = budget
        self._started = time.monotonic()
        self._seen: set[str] = set()
        self.steps = 0
        self.calls = 0
        self.tokens = 0

    @property
    def remaining_s(self) -> float:
        return max(0.0, self._budget.timeout_s - (time.monotonic() - self._started))

    def consume_tokens(self, amount: int) -> None:
        self.tokens += max(0, amount)
        if self.tokens > self._budget.max_tokens:
            raise BudgetExceeded("investigation token budget exhausted")  # noqa: TRY003 - contextual domain error

    def step(self) -> None:
        if (
            self.steps >= self._budget.max_steps
            or time.monotonic() - self._started >= self._budget.timeout_s
        ):
            raise BudgetExceeded("investigation step/time budget exhausted")  # noqa: TRY003 - contextual domain error
        self.steps += 1

    def admit(self, invocation: ToolInvocation) -> None:
        key = invocation.name + json.dumps(invocation.arguments, sort_keys=True)
        if self.calls >= self._budget.max_tool_calls or key in self._seen:
            raise BudgetExceeded("tool budget exhausted or duplicate call rejected")  # noqa: TRY003 - contextual domain error
        self._seen.add(key)
        self.calls += 1
