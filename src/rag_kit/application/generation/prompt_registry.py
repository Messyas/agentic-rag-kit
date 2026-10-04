"""Versioned pack prompt templates and content hashes."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

if TYPE_CHECKING:
    from pathlib import Path


class PromptRegistry:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._environment = Environment(
            loader=FileSystemLoader(directory),
            undefined=StrictUndefined,
            autoescape=False,  # noqa: S701 - plain-text inference prompts, never HTML
        )

    def render(self, name: str, variables: dict[str, Any]) -> str:
        return self._environment.get_template(name).render(**variables)

    def digest(self, name: str) -> str:
        return hashlib.sha256((self._directory / name).read_bytes()).hexdigest()
