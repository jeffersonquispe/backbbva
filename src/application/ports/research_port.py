from __future__ import annotations

from typing import Protocol

from src.application.dtos.research_dtos import (
    ResearchRequest,
    ResearchResult,
)


class ResearchAgent(Protocol):
    def research(self, request: ResearchRequest) -> ResearchResult: ...
