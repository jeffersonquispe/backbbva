from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class AgentInsightKind(StrEnum):
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    CONSTRAINT = "constraint"
    PREFERENCE = "preference"
    DIRECTIVE = "directive"
    QUESTION = "question"
    DECISION = "decision"


class AgentInsightStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    APPLIED = "APPLIED"
    REFUTED = "REFUTED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class AgentInsight:
    session_id: str
    insight_id: str
    kind: AgentInsightKind
    statement: str
    scope: dict[str, str]
    status: AgentInsightStatus
    proposed_by: str
    author_id: str
    source_message_id: str | None
    created_at: datetime
    updated_at: datetime
    confidence: float | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    supersedes_id: str | None = None
    expires_at: datetime | None = None
    rev: int = 0


class AgentInsightRepository(Protocol):
    def create(self, insight: AgentInsight) -> AgentInsight: ...

    def get(self, session_id: str, insight_id: str) -> AgentInsight | None: ...

    def update(self, insight: AgentInsight, expected_rev: int) -> AgentInsight: ...

    def list_for_session(
        self,
        session_id: str,
        status: AgentInsightStatus | None = None,
        limit: int = 100,
    ) -> list[AgentInsight]: ...

    def list_active_by_scope(
        self, scope_key: str, limit: int = 100
    ) -> list[AgentInsight]: ...
