from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class AgentHypothesisStatus(StrEnum):
    ACTIVE = "ACTIVE"
    VALIDATED = "VALIDATED"
    REFUTED = "REFUTED"
    NONCONCLUSIVE = "NONCONCLUSIVE"


@dataclass(frozen=True)
class AgentHypothesis:
    session_id: str
    hypothesis_id: str
    statement: str
    scope: dict[str, str]
    priority: int
    status: AgentHypothesisStatus
    created_at: datetime
    updated_at: datetime
    source_insight_id: str | None = None
    evidence_id: str | None = None
    evidence_outcome: str | None = None
    rev: int = 0
    # Candidates that must be concluded before this one runs (combinations).
    depends_on: tuple[str, ...] = ()
    # Insights that belong to this candidate specifically.
    insight_ids: tuple[str, ...] = ()
    # Final verdict, evidence, decision and recommendation, written once.
    conclusion: dict[str, Any] = field(default_factory=dict)


class AgentHypothesisRepository(Protocol):
    def create(self, hypothesis: AgentHypothesis) -> AgentHypothesis: ...

    def list_for_session(
        self, session_id: str, limit: int = 100
    ) -> list[AgentHypothesis]: ...

    def update(
        self, hypothesis: AgentHypothesis, expected_rev: int
    ) -> AgentHypothesis: ...
