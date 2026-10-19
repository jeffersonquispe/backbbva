from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AgentLink:
    session_id: str
    source_type: str
    source_id: str
    relation: str
    target_type: str
    target_id: str
    created_at: datetime
    expires_at: datetime | None = None


class AgentLinkRepository(Protocol):
    def create_once(self, link: AgentLink) -> AgentLink: ...

    def list_from(
        self, session_id: str, source_type: str, source_id: str
    ) -> list[AgentLink]: ...

    def list_to(self, target_type: str, target_id: str) -> list[AgentLink]: ...
