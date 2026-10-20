from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


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


class AgentHypothesisRepository(Protocol):
    def create(self, hypothesis: AgentHypothesis) -> AgentHypothesis: ...

    def list_for_session(self, session_id: str, limit: int = 100) -> list[AgentHypothesis]: ...

    def update(self, hypothesis: AgentHypothesis, expected_rev: int) -> AgentHypothesis: ...
