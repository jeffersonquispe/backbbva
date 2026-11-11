from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.llm_catalog_port import LLMCatalogPort
from src.application.use_cases.llm.resolve_element_llm import ResolveElementLLM
from src.domain.llm.catalog import (
    LLM_ELEMENTS,
    WORKFLOW_LLM_ELEMENTS,
    LLMCatalogEntry,
)


@dataclass(frozen=True)
class LLMElementInfo:
    element: str
    group: str  # "workflow" | "support"
    default_deployment: str


@dataclass(frozen=True)
class GetLLMCatalogOutput:
    entries: tuple[LLMCatalogEntry, ...]
    elements: tuple[LLMElementInfo, ...]


class GetLLMCatalogUseCase:
    """What the selectors need: the catalog and each element's default."""

    def __init__(self, catalog: LLMCatalogPort, resolver: ResolveElementLLM) -> None:
        self._catalog = catalog
        self._resolver = resolver

    def execute(self) -> GetLLMCatalogOutput:
        return GetLLMCatalogOutput(
            entries=self._catalog.get().entries,
            elements=tuple(
                LLMElementInfo(
                    element=element,
                    group="workflow" if element in WORKFLOW_LLM_ELEMENTS else "support",
                    default_deployment=self._resolver.default_for(element),
                )
                for element in LLM_ELEMENTS
            ),
        )
