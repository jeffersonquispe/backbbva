from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.llm.catalog import LLMCatalog


class LLMCatalogPort(ABC):
    """Read-only source of the LLM deployments an element may select."""

    @abstractmethod
    def get(self) -> LLMCatalog: ...
