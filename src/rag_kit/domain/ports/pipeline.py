"""Analysis pipeline strategy protocol."""

from typing import Protocol, runtime_checkable

from rag_kit.domain.analysis import AnalysisResult, Subject


@runtime_checkable
class AnalysisPipeline(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...
    async def analyze(self, subject: Subject) -> AnalysisResult: ...
