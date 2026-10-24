from __future__ import annotations

from abc import ABC, abstractmethod


class ProjectGraphSemanticSearch(ABC):
    @abstractmethod
    def rank(self, query: str, limit: int) -> list[str]:
        """Node ids of the project graph by embedding similarity, best first."""
        raise NotImplementedError
