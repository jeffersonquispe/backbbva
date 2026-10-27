from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentDraftResourcePort(ABC):
    """Read and apply the small set of resources drafted by the assistant."""

    @abstractmethod
    def context(self, resource: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def verify(
        self, resource: str, draft: dict[str, Any]
    ) -> list[tuple[str, str, str | None]]:
        raise NotImplementedError

    @abstractmethod
    def create(self, resource: str, draft: dict[str, Any]) -> str:
        raise NotImplementedError
