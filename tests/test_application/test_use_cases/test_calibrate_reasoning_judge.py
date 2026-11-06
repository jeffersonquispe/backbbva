from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.application.use_cases.metrics.calibrate_reasoning_judge import (
    review_sample,
    score,
)

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def _record(status=ReasoningEvaluationStatus.EVALUATED):
    return AlertReasoningEvaluationRecord(
        alert_id=uuid4(),
        workflow_execution_id=uuid4(),
        status=status,
        hallucination=False,
        data_use_correct=True,
        rationale="",
        judge_model="judge",
        evaluated_at=NOW,
    )


def test_the_sample_is_reproducible_valid_only_and_bounded() -> None:
    records = [_record() for _ in range(40)] + [
        _record(ReasoningEvaluationStatus.INVALID) for _ in range(5)
    ]

    first = review_sample(records, 10, seed=7)
    again = review_sample(list(reversed(records)), 10, seed=7)

    assert [r.alert_id for r in first] == [r.alert_id for r in again]
    assert len(first) == 10 and len({r.alert_id for r in first}) == 10
    assert all(r.status == ReasoningEvaluationStatus.EVALUATED for r in first)
    assert [r.alert_id for r in review_sample(records, 10, seed=8)] != [
        r.alert_id for r in first
    ]
    assert len(review_sample(records, 1_000, seed=1)) == 40


def test_perfect_agreement_has_kappa_one() -> None:
    result = score(
        {"hallucination": [(True, True), (False, False), (True, True), (False, False)]}
    )[0]

    assert (result.compared, result.agreement, result.cohen_kappa) == (4, 1.0, 1.0)
    assert (result.judge_true_human_false, result.judge_false_human_true) == (0, 0)
    assert result.usable


def test_errors_are_counted_taking_the_human_as_the_truth() -> None:
    pairs = (
        [(True, True)] * 3
        + [(True, False)] * 2
        + [(False, True)]
        + [(False, False)] * 4
    )

    result = score({"hallucination": pairs})[0]

    assert result.compared == 10
    assert result.agreement == pytest.approx(0.7)
    assert (result.judge_true_human_false, result.judge_false_human_true) == (2, 1)
    # observed .7, expected .5*.4 + .5*.6 = .5 -> kappa .4: not good enough to trust.
    assert result.cohen_kappa == pytest.approx(0.4)
    assert not result.usable


def test_a_judge_that_always_says_the_same_has_no_kappa_to_trust() -> None:
    result = score({"data_use_correct": [(True, True), (True, True), (True, True)]})[1]

    assert result.agreement == 1.0
    assert result.cohen_kappa is None and not result.usable  # chance explains it all


def test_a_criterion_without_human_answers_is_empty() -> None:
    first, second = score({})

    assert (first.compared, first.agreement, first.cohen_kappa) == (0, None, None)
    assert second.criterion == "data_use_correct"
