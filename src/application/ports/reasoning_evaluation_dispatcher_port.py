from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ReasoningEvaluationDispatchRef:
    backend: str
    external_id: str | None = None


class ReasoningEvaluationDispatcher:
    """Fire-and-forget: hands a finished, sampled alert to the LLM-judge
    (EvaluateAlertReasoning) so it runs off the alert review's critical
    path. The judge re-reads the persisted run, so only ids travel."""

    def dispatch(
        self, alert_id: UUID, workflow_execution_id: UUID
    ) -> ReasoningEvaluationDispatchRef:
        raise NotImplementedError
