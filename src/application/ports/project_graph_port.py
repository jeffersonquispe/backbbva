from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.project_graph.entities import ProjectGraph


class ProjectGraphRepository(ABC):
    @abstractmethod
    def load(self) -> ProjectGraph:
        """Return the project graph (views, components, actions, assets...)."""
        raise NotImplementedError
