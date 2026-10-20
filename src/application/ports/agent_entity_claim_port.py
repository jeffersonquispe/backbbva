from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AgentEntityClaim:
    entity_key: str
    session_id: str
    claimed_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    reason: str


class AgentEntityClaimRepository(Protocol):
    def claim(self, claim: AgentEntityClaim) -> AgentEntityClaim: ...

    def list_by_entity(self, entity_key: str, limit: int = 50) -> list[AgentEntityClaim]: ...

    def list_by_session(self, session_id: str, limit: int = 100) -> list[AgentEntityClaim]: ...

    def release_session(self, session_id: str) -> int: ...
