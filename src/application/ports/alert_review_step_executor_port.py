from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AlertReviewStepExecutor(ABC):
    """Runs one named step of the alert review pipeline.

    The workflow use case owns *when* a step runs (order, feedback loops,
    status, metrics); an executor owns *what* it does (which agent/use case
    is composed, with which tools and prompts). ``context`` is the run's
    shared state, mutated across steps.
    """

    @abstractmethod
    def execute(self, step_name: str, context: dict[str, Any]) -> Any:
        """Run ``step_name`` and return its output (a dataclass or dict)."""
        raise NotImplementedError

    @abstractmethod
    def enrich(self, step_name: str, context: dict[str, Any]) -> dict[str, Any]:
        """Context enrichment that follows ``step_name`` but is not itself a
        persisted step (e.g. segment resolution after ``pre_process``)."""
        raise NotImplementedError
