"""Read the LLM-judge verdicts (D6): one alert's explanation, and a filtered
list of the evaluated ones. Read-only; the judge itself is
``EvaluateAlertReasoning``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from src.application.ports.alert_port import AlertRepository
from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    AlertReasoningEvaluationRepository,
    ReasoningEvaluationStatus,
)
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.use_cases.metrics.evaluate_alert_reasoning import (
    is_sampled_for_evaluation,
)
from src.domain.alerts.entities import AlertOrigin

MAX_RANGE_DAYS = 31
MAX_LIST_LIMIT = 200
# Origins that never go to the judge (isolated from operational metrics).
UNJUDGED_ORIGINS = frozenset(
    {AlertOrigin.TEST_RUN.value, AlertOrigin.OPTIMIZER_EVALUATION.value}
)


class ReasoningEvaluationState(StrEnum):
    EVALUATED = "evaluated"
    INVALID = "invalid"
    # Selected by the current sample rate but no verdict yet (still in the
    # queue, or the alert has not finished).
    PENDING = "pending"
    # Not selected: the judge only looks at a random share of alerts.
    NOT_SAMPLED = "not_sampled"
    # Test runs and optimizer evaluations are never judged.
    NOT_APPLICABLE = "not_applicable"


class ReasoningEvaluationAlertNotFoundError(Exception):
    pass


class ReasoningEvaluationRangeError(ValueError):
    pass


@dataclass(frozen=True)
class AlertReasoningEvaluationView:
    alert_id: UUID
    state: ReasoningEvaluationState
    evaluation: AlertReasoningEvaluationRecord | None


class GetAlertReasoningEvaluation:
    def __init__(
        self,
        evaluations: AlertReasoningEvaluationRepository,
        alerts: AlertRepository,
        settings: OperationalSettingsRepository,
    ) -> None:
        self._evaluations = evaluations
        self._alerts = alerts
        self._settings = settings

    def execute(self, alert_id: UUID) -> AlertReasoningEvaluationView:
        stored = self._evaluations.get(alert_id)
        if stored is not None:
            state = (
                ReasoningEvaluationState.INVALID
                if stored.status == ReasoningEvaluationStatus.INVALID
                else ReasoningEvaluationState.EVALUATED
            )
            return AlertReasoningEvaluationView(alert_id, state, stored)
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise ReasoningEvaluationAlertNotFoundError(str(alert_id))
        # The origin lives on the metrics snapshot, written when the alert arrives.
        origin = alert.metrics.origin if alert.metrics is not None else None
        if (origin or "") in UNJUDGED_ORIGINS:
            state = ReasoningEvaluationState.NOT_APPLICABLE
        elif is_sampled_for_evaluation(
            alert_id, self._settings.get().reasoning_evaluation_sample_rate
        ):
            state = ReasoningEvaluationState.PENDING
        else:
            state = ReasoningEvaluationState.NOT_SAMPLED
        return AlertReasoningEvaluationView(alert_id, state, None)


class ListReasoningEvaluations:
    def __init__(self, evaluations: AlertReasoningEvaluationRepository) -> None:
        self._evaluations = evaluations

    def execute(
        self,
        *,
        from_day: date,
        to_day: date,
        hallucination: bool | None = None,
        data_use_correct: bool | None = None,
        status: ReasoningEvaluationStatus | None = None,
        limit: int = 50,
    ) -> list[AlertReasoningEvaluationRecord]:
        if to_day < from_day:
            raise ReasoningEvaluationRangeError("to_day is before from_day")
        if (to_day - from_day).days + 1 > MAX_RANGE_DAYS:
            raise ReasoningEvaluationRangeError(
                f"the range is limited to {MAX_RANGE_DAYS} days"
            )
        limit = max(1, min(limit, MAX_LIST_LIMIT))
        # Filters apply after the day query, so ask for more than `limit`.
        candidates = self._evaluations.list_between(
            from_day, to_day, limit=MAX_LIST_LIMIT * 5
        )
        matching = [
            record
            for record in candidates
            if (hallucination is None or record.hallucination is hallucination)
            and (
                data_use_correct is None or record.data_use_correct is data_use_correct
            )
            and (status is None or record.status == status)
        ]
        return matching[:limit]
