from __future__ import annotations

from abc import ABC, abstractmethod


class AgentChatDispatcher(ABC):
    """Hands one stored chat turn to a worker, which writes the assistant reply."""

    @abstractmethod
    def dispatch(
        self,
        *,
        session_id: str,
        owner_id: str,
        client_message_id: str,
        page_path: str,
        role: str,
    ) -> None:
        raise NotImplementedError
