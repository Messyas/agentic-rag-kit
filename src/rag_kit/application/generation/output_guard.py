"""Composable guardrails for source-backed structured output."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Protocol, cast

from pydantic import BaseModel, Field

from rag_kit.domain.analysis import Claim, GuardViolationInfo

if TYPE_CHECKING:
    from collections.abc import Sequence


class ClaimsProvider(Protocol):
    def claims(self) -> Sequence[Claim]: ...
    def figures_list(self) -> Sequence[tuple[str, Any]]: ...


class GuardContext(BaseModel):
    allowed_source_ids: frozenset[str]
    trusted_numbers: Mapping[str, str] = Field(default_factory=dict)


class OutputGuard(Protocol):
    name: str

    def check(self, output: BaseModel, context: GuardContext) -> list[GuardViolationInfo]: ...


def _issue(guard: str, code: str, message: str) -> GuardViolationInfo:
    return GuardViolationInfo(guard=guard, code=code, message=message)


def _claims(output: BaseModel) -> Sequence[Claim]:
    method = getattr(output, "claims", None)
    return cast("Sequence[Claim]", method()) if callable(method) else ()


class SourceExistsGuard:
    name = "source_exists"

    def check(self, output: BaseModel, context: GuardContext) -> list[GuardViolationInfo]:
        issues: list[GuardViolationInfo] = []
        for claim in _claims(output):
            if not claim.source_ids:
                issues.append(_issue(self.name, "no_source", "Claim has no evidence source."))
            if set(claim.source_ids) - context.allowed_source_ids:
                issues.append(
                    _issue(self.name, "unknown_source", "Claim cites unavailable evidence.")
                )
        return issues


class NumberParityGuard:
    name = "number_parity"

    def check(self, output: BaseModel, context: GuardContext) -> list[GuardViolationInfo]:
        issues: list[GuardViolationInfo] = []
        for label, value in cast("ClaimsProvider", output).figures_list():
            trusted = context.trusted_numbers.get(label)
            try:
                valid = trusted is not None and Decimal(str(value)) == Decimal(trusted)
            except (InvalidOperation, ValueError):
                valid = False
            if not valid:
                issues.append(
                    _issue(
                        self.name,
                        "figure_mismatch",
                        "Figure label/value differs from deterministic data.",
                    )
                )
        return issues


class AbstentionGuard:
    name = "abstention"

    def check(self, output: BaseModel, context: GuardContext) -> list[GuardViolationInfo]:  # noqa: ARG002 - port signature retained
        data = output.model_dump()
        insufficient = data.get("outcome") == "insufficient_evidence"
        invalid = (insufficient and (data.get("hypotheses") or not data.get("gaps"))) or (
            not insufficient and not data.get("context")
        )
        return (
            [_issue(self.name, "invalid_outcome", "Outcome does not match evidence/gaps.")]
            if invalid
            else []
        )


class HypothesisLabelGuard:
    name = "hypothesis_label"

    def check(self, output: BaseModel, context: GuardContext) -> list[GuardViolationInfo]:  # noqa: ARG002 - port signature retained
        unconditional = ("foi causado por", "a causa e", "a causa é")
        hedges = ("possível", "possivel", "pode", "hipótese", "hipotese", "provável", "provavel")
        issues: list[GuardViolationInfo] = []
        for item in output.model_dump().get("hypotheses", []):
            text = item["statement"].casefold()
            if not item.get("confidence") or (
                any(phrase in text for phrase in unconditional)
                and not any(phrase in text for phrase in hedges)
            ):
                issues.append(
                    _issue(
                        self.name, "unqualified_cause", "Hypothesis states an unqualified cause."
                    )
                )
        return issues


class DomainGuard:
    name = "domain"

    def __init__(self, allowed: Sequence[str]) -> None:
        self._allowed = frozenset(allowed)

    def check(self, output: BaseModel, context: GuardContext) -> list[GuardViolationInfo]:  # noqa: ARG002 - port signature retained
        record: dict[str, Any] = output.model_dump().get("proposed_record") or {}
        defect = record.get("defect_type")
        return (
            [_issue(self.name, "unknown_defect", "Defect is outside the controlled vocabulary.")]
            if defect and defect not in self._allowed
            else []
        )


class InjectionEchoGuard:
    name = "injection_echo"

    def check(self, output: BaseModel, context: GuardContext) -> list[GuardViolationInfo]:  # noqa: ARG002 - port signature retained
        markers = (
            "ignore previous instructions",
            "ignore as regras",
            "ignore the instructions",
            "ignore instruções",
        )
        text = output.model_dump_json().casefold()
        return (
            [_issue(self.name, "injection_echo", "Output repeats an injection marker.")]
            if any(marker in text for marker in markers)
            else []
        )


class GuardChain:
    def __init__(self, guards: Sequence[OutputGuard]) -> None:
        self._guards = tuple(guards)

    def run(self, output: BaseModel, context: GuardContext) -> list[GuardViolationInfo]:
        issues: list[GuardViolationInfo] = []
        for guard in self._guards:
            try:
                issues.extend(guard.check(output, context))
            except Exception:
                issues.append(_issue(guard.name, "guard_failed", "Guard execution failed."))
        return issues


def parse_ptbr_number(token: str) -> Decimal | None:
    cleaned = token.strip().replace("R$", "").replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None
