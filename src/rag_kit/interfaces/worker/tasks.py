"""Worker-callable use case receiving dependencies from the host scope."""

from rag_kit.application.facade import AnalysisFacade
from rag_kit.domain.analysis import AnalysisResult, Subject


async def analyze_subject(facade: AnalysisFacade, subject: Subject) -> AnalysisResult:
    return await facade.analyze(subject)
