"""Discover domain packs without import-time registration side effects."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points

from rag_kit.application.pack import PackSpec
from rag_kit.domain.errors import ConfigurationError


def load_pack(name: str) -> PackSpec:
    matches = [entry for entry in entry_points(group="rag_kit.packs") if entry.name == name]
    try:
        factory = matches[0].load() if matches else import_module(f"packs.{name}").build_pack
        pack = factory()
        if not isinstance(pack, PackSpec):
            raise ConfigurationError("Pack factory must return PackSpec")  # noqa: TRY003 - contextual domain error
        pack.validate()
    except (ImportError, AttributeError, ValueError) as error:
        raise ConfigurationError(f"Cannot load pack {name}: {error}") from error  # noqa: TRY003 - contextual domain error
    return pack


def load_packs(names: tuple[str, ...]) -> dict[str, PackSpec]:
    return {name: load_pack(name) for name in names}
