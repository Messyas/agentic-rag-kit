"""Optional FastAPI interface accepting an injected analysis facade."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from rag_kit.domain.analysis import AnalysisResult, Subject

if TYPE_CHECKING:
    from rag_kit.application.facade import AnalysisFacade


def build_router(facade: AnalysisFacade) -> Any:
    fastapi = import_module("fastapi")
    router: Any = fastapi.APIRouter(prefix="/analysis", tags=["analysis"])

    async def analyze(subject: Subject) -> AnalysisResult:
        return await facade.analyze(subject)

    router.add_api_route("", analyze, methods=["POST"], response_model=AnalysisResult)
    return router
