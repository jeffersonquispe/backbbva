from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AgentMessage:
    session_id: str
    client_message_id: str
    message_id: str
    seq: int
    role: str
    content: str
    author_id: str
    created_at: datetime
    redaction_counts: dict[str, int] = field(default_factory=dict)
    extracted_insight_ids: tuple[str, ...] = ()
    run_id: str | None = None
    expires_at: datetime | None = None
    # Assistant messages only: places the user can open ({id, kind, label, path})
    # and the project-map nodes the answer was grounded on ({id, kind, label}).
    references: tuple[dict[str, str], ...] = ()
    context_used: tuple[dict[str, str], ...] = ()


class AgentMessageRepository(Protocol):
    def create_once(self, message: AgentMessage) -> AgentMessage: ...

    def get_by_client_message_id(
        self, session_id: str, client_message_id: str
    ) -> AgentMessage | None: ...

    def list_after_seq(
        self, session_id: str, after_seq: int, limit: int = 50
    ) -> list[AgentMessage]: ...

    def count_for_session(self, session_id: str) -> int: ...
