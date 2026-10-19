from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AgentBudgetEntry:
    session_id: str
    entry_id: str
    entry_type: str
    resource: str
    amount: int
    actor: str
    reason: str
    created_at: datetime


class AgentBudgetLedgerRepository(Protocol):
    def append(self, entry: AgentBudgetEntry) -> AgentBudgetEntry: ...

    def list_for_session(
        self, session_id: str, limit: int = 100
    ) -> list[AgentBudgetEntry]: ...

    def reserve(
        self, session_id: str, resource: str, amount: int, limit: int
    ) -> bool: ...
