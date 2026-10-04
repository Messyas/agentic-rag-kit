"""Stable output masking and content-safe logging redaction."""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping


class Masker:
    def __init__(self, key: bytes, fields: frozenset[str]) -> None:
        if not key:
            raise ValueError("masking requires a local secret")  # noqa: TRY003 - contextual domain error
        self._key = key
        self._fields = fields

    def token(self, value: str) -> str:
        return (
            "MASK-" + hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()[:12].upper()
        )

    def mask(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {
            name: self.token(str(value)) if name in self._fields and value is not None else value
            for name, value in data.items()
        }


def redact_event(
    logger: object,  # noqa: ARG001 - structlog processor contract
    method_name: str,  # noqa: ARG001 - structlog processor contract
    event: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    for field in ("prompt", "response", "messages", "content"):
        value = event.pop(field, None)
        if value is not None:
            event[field + "_hash"] = hashlib.sha256(str(value).encode()).hexdigest()
    return event
