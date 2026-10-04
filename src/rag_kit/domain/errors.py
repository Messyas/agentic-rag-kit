"""Typed errors crossing domain and adapter boundaries."""


class RagKitError(Exception):
    """Base error for expected kit failures."""


class ConfigurationError(RagKitError): ...


class IllegalTransition(RagKitError): ...  # noqa: N818 - public domain name is specified by the backlog


class IngestionError(RagKitError): ...


class LLMError(RagKitError): ...


class LLMTransientError(LLMError): ...


class LLMPermanentError(LLMError): ...


class LLMTimeoutError(LLMTransientError): ...


class CircuitOpenError(LLMError): ...


class LLMOutputError(LLMError): ...


class RetrievalError(RagKitError): ...


class StoreError(RagKitError): ...


class GuardrailError(RagKitError): ...


class ToolError(RagKitError): ...


class BudgetExceeded(RagKitError): ...  # noqa: N818 - public domain name is specified by the backlog


class NodeError(RagKitError):
    """Failure associated with a named workflow node."""

    def __init__(self, node_name: str, cause: Exception) -> None:
        self.node_name = node_name
        self.cause = cause
        super().__init__(f"node {node_name!r} failed: {cause}")
