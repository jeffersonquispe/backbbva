from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.application.use_cases.metrics.read_reasoning_evaluations import (
    GetAlertReasoningEvaluation,
    ListReasoningEvaluations,
    ReasoningEvaluationAlertNotFoundError,
    ReasoningEvaluationRangeError,
    ReasoningEvaluationState,
)

NOW = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)


def _record(
    alert_id: UUID | None = None,
    *,
    hallucination: bool | None = False,
    data_use_correct: bool | None = True,
    status: ReasoningEvaluationStatus = ReasoningEvaluationStatus.EVALUATED,
    at: datetime = NOW,
) -> AlertReasoningEvaluationRecord:
    return AlertReasoningEvaluationRecord(
        alert_id=alert_id or uuid4(),
        workflow_execution_id=uuid4(),
        status=status,
        hallucination=hallucination,
        data_use_correct=data_use_correct,
        rationale="ok",
        judge_model="judge",
        evaluated_at=at,
    )


class InMemoryEvaluations:
    def __init__(self, *records: AlertReasoningEvaluationRecord) -> None:
        self.records = {r.alert_id: r for r in records}
        self.asked: list[tuple[date, date, int]] = []

    def get(self, alert_id):
        return self.records.get(alert_id)

    def list_between(self, from_day, to_day, *, limit):
        self.asked.append((from_day, to_day, limit))
        return sorted(self.records.values(), key=lambda r: r.evaluated_at, reverse=True)

    def create(self, record):
        return record


class InMemoryAlerts:
    def __init__(self, **origins: str | None) -> None:
        self.origins = origins

    def get(self, alert_id: UUID):
        key = str(alert_id)
        if key not in self.origins:
            return None
        origin = self.origins[key]
        # The origin lives on the metrics snapshot (None before it is written).
        return SimpleNamespace(
            metrics=SimpleNamespace(origin=origin) if origin is not None else None
        )


class InMemoryOperationalSettings:
    def __init__(self, rate: float) -> None:
        self.rate = rate

    def get(self):
        return SimpleNamespace(reasoning_evaluation_sample_rate=self.rate)


def _get(evaluations, alerts, rate=1.0) -> GetAlertReasoningEvaluation:
    return GetAlertReasoningEvaluation(
        evaluations, alerts, InMemoryOperationalSettings(rate)
    )


def test_a_stored_verdict_is_returned_with_its_state() -> None:
    good, bad = _record(), _record(status=ReasoningEvaluationStatus.INVALID)
    use_case = _get(InMemoryEvaluations(good, bad), InMemoryAlerts())

    assert use_case.execute(good.alert_id).state == ReasoningEvaluationState.EVALUATED
    assert use_case.execute(bad.alert_id).state == ReasoningEvaluationState.INVALID
    assert use_case.execute(good.alert_id).evaluation == good


def test_without_a_verdict_it_says_why() -> None:
    prod, test_run, optimizer = uuid4(), uuid4(), uuid4()
    alerts = InMemoryAlerts(
        **{
            str(prod): "production",
            str(test_run): "test_run",
            str(optimizer): "optimizer_evaluation",
        }
    )

    sampled = _get(InMemoryEvaluations(), alerts, rate=1.0)
    unsampled = _get(InMemoryEvaluations(), alerts, rate=0.0)

    assert sampled.execute(prod).state == ReasoningEvaluationState.PENDING
    assert unsampled.execute(prod).state == ReasoningEvaluationState.NOT_SAMPLED
    # Test runs and optimizer evaluations are never judged, whatever the rate.
    assert sampled.execute(test_run).state == ReasoningEvaluationState.NOT_APPLICABLE
    assert sampled.execute(optimizer).state == ReasoningEvaluationState.NOT_APPLICABLE
    assert sampled.execute(prod).evaluation is None


def test_an_alert_without_a_metrics_snapshot_is_treated_as_judgeable() -> None:
    bare = uuid4()

    view = _get(InMemoryEvaluations(), InMemoryAlerts(**{str(bare): None})).execute(
        bare
    )

    assert view.state == ReasoningEvaluationState.PENDING


def test_an_unknown_alert_without_verdict_is_not_found() -> None:
    with pytest.raises(ReasoningEvaluationAlertNotFoundError):
        _get(InMemoryEvaluations(), InMemoryAlerts()).execute(uuid4())


def test_listing_filters_by_verdict_and_status_and_bounds_the_limit() -> None:
    halluc = _record(hallucination=True, data_use_correct=False)
    clean = _record()
    invalid = _record(
        hallucination=None,
        data_use_correct=None,
        status=ReasoningEvaluationStatus.INVALID,
    )
    evaluations = InMemoryEvaluations(halluc, clean, invalid)
    use_case = ListReasoningEvaluations(evaluations)
    day = date(2026, 11, 5)

    def ids(**filters):
        return {
            r.alert_id for r in use_case.execute(from_day=day, to_day=day, **filters)
        }

    assert ids() == {halluc.alert_id, clean.alert_id, invalid.alert_id}
    assert ids(hallucination=True) == {halluc.alert_id}
    assert ids(hallucination=False) == {clean.alert_id}
    assert ids(data_use_correct=False) == {halluc.alert_id}
    assert ids(status=ReasoningEvaluationStatus.INVALID) == {invalid.alert_id}
    assert len(use_case.execute(from_day=day, to_day=day, limit=1)) == 1
    use_case.execute(from_day=day, to_day=day, limit=10_000)
    assert evaluations.asked[0][:2] == (day, day)


def test_the_listing_range_is_validated() -> None:
    use_case = ListReasoningEvaluations(InMemoryEvaluations())

    with pytest.raises(ReasoningEvaluationRangeError):
        use_case.execute(from_day=date(2026, 11, 5), to_day=date(2026, 11, 4))
    with pytest.raises(ReasoningEvaluationRangeError):
        use_case.execute(from_day=date(2026, 10, 1), to_day=date(2026, 11, 5))
    use_case.execute(from_day=date(2026, 10, 6), to_day=date(2026, 11, 5))  # 31 days
