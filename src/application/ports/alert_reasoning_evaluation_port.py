from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ReasoningEvaluationStatus(StrEnum):
    # The judge returned both verdicts.
    EVALUATED = "evaluated"
    # The judge's answer could not be parsed - stored for audit, counted
    # apart (invalid_count) so it never dilutes the rates.
    INVALID = "invalid"


@dataclass
class AlertReasoningEvaluationRecord:
    """One LLM-judge verdict on a finished alert's reasoning (D6): did the
    steps state facts the evidence they had doesn't support
    (hallucination), and did they use that evidence correctly
    (data_use_correct). One per alert - the first stored verdict wins."""

    alert_id: UUID
    workflow_execution_id: UUID
    status: ReasoningEvaluationStatus
    hallucination: bool | None
    data_use_correct: bool | None
    rationale: str
    judge_model: str
    evaluated_at: datetime
    input_tokens: int = 0
    output_tokens: int = 0


class AlertReasoningEvaluationRepository(Protocol):
    def create(
        self, record: AlertReasoningEvaluationRecord
    ) -> AlertReasoningEvaluationRecord:
        """Stores `record` unless the alert already has a verdict; returns
        the stored one either way (first writer wins)."""
        ...

    def get(self, alert_id: UUID) -> AlertReasoningEvaluationRecord | None: ...
