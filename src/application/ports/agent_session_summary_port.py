from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AgentSessionSummary:
    session_id: str
    version: int
    content: dict[str, object]
    covers_seq_from: int
    covers_seq_to: int
    created_at: datetime
    expires_at: datetime | None = None


class AgentSessionSummaryRepository(Protocol):
    def create(self, summary: AgentSessionSummary) -> AgentSessionSummary: ...

    def get_latest(self, session_id: str) -> AgentSessionSummary | None: ...

    def get(self, session_id: str, version: int) -> AgentSessionSummary | None: ...
