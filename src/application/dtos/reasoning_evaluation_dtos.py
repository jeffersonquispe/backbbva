from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
)


@dataclass
class EvaluateAlertReasoningInput:
    alert_id: UUID
    workflow_execution_id: UUID


@dataclass
class EvaluateAlertReasoningOutput:
    # None when there was nothing to judge (alert/run missing, or no
    # reasoning step produced an output - e.g. a deterministic discard).
    evaluation: AlertReasoningEvaluationRecord | None
    # True when this call added the verdict to the rollups; False when it
    # was already counted (retry / redelivery) or there was no verdict.
    counted: bool = False
