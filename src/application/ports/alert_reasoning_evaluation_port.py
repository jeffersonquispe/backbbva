from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
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
    # Version of the judge prompt that produced the verdict, so results can be
    # compared across prompt changes ("v1" = the original, per-alert-only one).
    prompt_version: str = "v1"
    # Per reasoning step: {"hallucination": bool, "data_use_correct": bool,
    # "note": str}. Empty for v1 verdicts, which judged the alert as a whole.
    step_verdicts: dict[str, dict[str, object]] = field(default_factory=dict)
    # Judge calls made (2 when the first answer could not be parsed).
    attempts: int = 1


class AlertReasoningEvaluationRepository(Protocol):
    def create(
        self, record: AlertReasoningEvaluationRecord
    ) -> AlertReasoningEvaluationRecord:
        """Stores `record` unless the alert already has a verdict; returns
        the stored one either way (first writer wins)."""
        ...

    def get(self, alert_id: UUID) -> AlertReasoningEvaluationRecord | None: ...

    def list_between(
        self, from_day: date, to_day: date, *, limit: int
    ) -> list[AlertReasoningEvaluationRecord]:
        """Verdicts evaluated on the Bogotá days from_day..to_day (inclusive),
        newest first, at most ``limit``."""
        ...
