from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AgentConfirmation:
    confirmation_id: str
    session_id: str
    package_id: str
    item_id: str
    action: str
    content_hash: str
    confirmed_by: str
    confirmed_at: datetime
    status: str = "VALID"


class AgentConfirmationRepository(Protocol):
    def create(self, confirmation: AgentConfirmation) -> AgentConfirmation: ...

    def list_for_session(
        self, session_id: str, limit: int = 100
    ) -> list[AgentConfirmation]: ...
