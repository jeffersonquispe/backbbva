from __future__ import annotations

from dataclasses import dataclass, field
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
    # Rows are created only after the user explicitly applies a verified draft.
    status: str = "CONFIRMED"
    role: str = "unknown"
    base_version: str | None = None
    verification_states: dict[str, str] = field(default_factory=dict)
    source_message_id: str | None = None


class AgentConfirmationRepository(Protocol):
    def create(self, confirmation: AgentConfirmation) -> AgentConfirmation: ...

    def list_for_session(
        self, session_id: str, limit: int = 100
    ) -> list[AgentConfirmation]: ...
