from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ReasoningEvaluationDispatchRef:
    backend: str
    external_id: str | None = None


class ReasoningEvaluationDispatcher(ABC):
    """Fire-and-forget announcement that an alert finished its review. The
    evaluator (not the alert flow) decides whether to judge it - sampling,
    origin, its own job state - so the alert flow never reads the evaluator's
    settings and never waits for it. Only ids travel."""

    def dispatch(
        self, alert_id: UUID, workflow_execution_id: UUID
    ) -> ReasoningEvaluationDispatchRef:
        raise NotImplementedError
