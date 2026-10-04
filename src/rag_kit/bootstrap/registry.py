"""Small typed factory registry used by the composition root."""

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from rag_kit.domain.errors import ConfigurationError

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._factories: dict[str, Callable[..., T]] = {}

    def register(self, key: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
        def decorator(factory: Callable[..., T]) -> Callable[..., T]:
            if key in self._factories:
                raise ConfigurationError(f"{self._kind} '{key}' registered twice")  # noqa: TRY003
            self._factories[key] = factory
            return factory

        return decorator

    def create(self, key: str, *args: Any, **kwargs: Any) -> T:
        try:
            factory = self._factories[key]
        except KeyError as exc:
            known = ", ".join(sorted(self._factories)) or "<none>"
            raise ConfigurationError(  # noqa: TRY003
                f"unknown {self._kind} '{key}'. Known: {known}"
            ) from exc
        return factory(*args, **kwargs)
