"""Explicit budgets for correction and guard repair."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowPolicy:
    max_corrections: int = 1
    max_guard_repairs: int = 1

    def __post_init__(self) -> None:
        if self.max_corrections < 0 or self.max_guard_repairs < 0:
            raise ValueError("workflow budgets must be nonnegative")  # noqa: TRY003 - contextual domain error
