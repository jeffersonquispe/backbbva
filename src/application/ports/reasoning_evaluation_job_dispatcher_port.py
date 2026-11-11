from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class ReasoningEvaluationJobDispatcher(ABC):
    """Puts one evaluation job on the evaluator's own queue."""

    @abstractmethod
    def enqueue(self, alert_id: UUID, workflow_execution_id: UUID) -> None:
        raise NotImplementedError
