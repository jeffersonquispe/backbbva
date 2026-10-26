from __future__ import annotations

from typing import Protocol

from src.domain.agents.finding import AgentFinding, AgentFindingKind

__all__ = ["AgentFinding", "AgentFindingKind", "AgentFindingRepository"]


class AgentFindingRepository(Protocol):
    def create_once(self, finding: AgentFinding) -> AgentFinding: ...

    def get(self, session_id: str, finding_id: str) -> AgentFinding | None: ...

    def list_for_session(self, session_id: str, limit: int = 100) -> list[AgentFinding]: ...
