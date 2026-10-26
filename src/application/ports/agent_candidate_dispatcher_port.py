from __future__ import annotations

from abc import ABC, abstractmethod


class AgentCandidateDispatcher(ABC):
    """Runs one planned optimizer candidate as its own job, outside the tick."""

    @abstractmethod
    def dispatch(self, session_id: str, iteration_number: int) -> None:
        raise NotImplementedError
