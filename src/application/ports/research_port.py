from __future__ import annotations

from typing import Protocol

from src.application.dtos.research_dtos import (
    HistoryOperation,
    ResearchRequest,
    ResearchResult,
)


class HistoryResearchPlanner(Protocol):
    """The optional LLM subagent plans only this closed operation language."""

    def plan(self, request: ResearchRequest) -> list[HistoryOperation]: ...


class VectorStoreRetriever(Protocol):
    """Adapter boundary for a promoted, already scoped vector store."""

    def search(
        self, query: str, *, asset_type: str, top_k: int
    ) -> list[dict[str, object]]: ...


class ResearchAgent(Protocol):
    def research(self, request: ResearchRequest) -> ResearchResult: ...
