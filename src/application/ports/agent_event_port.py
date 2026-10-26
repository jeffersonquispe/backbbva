from __future__ import annotations

from typing import Protocol

from src.domain.agents.event import (
    AgentEvent,
    AgentEventKind,
    AgentEventOutcome,
)

__all__ = [
    "AgentEvent",
    "AgentEventKind",
    "AgentEventOutcome",
    "AgentEventRepository",
]


class AgentEventRepository(Protocol):
    def append(self, event: AgentEvent) -> AgentEvent:
        """Store the event and assign the next per-session `seq` atomically."""
        ...

    def list_for_session(
        self, session_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> list[AgentEvent]:
        """Events in ascending `seq` order, strictly after `after_seq`."""
        ...

    def list_latest(self, session_id: str, limit: int = 20) -> list[AgentEvent]:
        """The most recent events, newest first."""
        ...
