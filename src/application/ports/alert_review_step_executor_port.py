from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.application.dtos.workflow_run_state import WorkflowRunState


class AlertReviewStepExecutor(ABC):
    """Runs one named step of the alert review pipeline.

    The workflow use case owns *when* a step runs (order, feedback loops,
    status, metrics); an executor owns *what* it does (which agent/use case
    is composed, with which tools and prompts). ``context`` is the run's
    shared state, mutated across steps.
    """

    @abstractmethod
    def execute(self, step_name: str, context: WorkflowRunState) -> Any:
        """Run ``step_name`` and return its output (a dataclass or dict)."""
        raise NotImplementedError

    @abstractmethod
    def enrich(self, step_name: str, context: WorkflowRunState) -> WorkflowRunState:
        """Context enrichment that follows ``step_name`` but is not itself a
        persisted step (e.g. segment resolution after ``pre_process``)."""
        raise NotImplementedError
