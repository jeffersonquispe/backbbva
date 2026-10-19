from __future__ import annotations

from typing import Protocol

from src.application.dtos.research_dtos import HistoryOperation, ResearchRequest


class HistoryResearchPlanner(Protocol):
    """An optional LLM planner plans only this closed operation language."""

    def plan(self, request: ResearchRequest) -> list[HistoryOperation]: ...
