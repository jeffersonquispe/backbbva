from __future__ import annotations

from src.application.use_cases.test_runs.classification_metrics import (
    compute_analyst_agreement_metrics,
    compute_ground_truth_metrics,
)


def test_analyst_agreement_returns_none_for_no_cases() -> None:
    assert compute_analyst_agreement_metrics([]) is None


def test_analyst_agreement_maps_unknown_to_risk_suspected() -> None:
    metrics = compute_analyst_agreement_metrics(
        [
            ("risk", "fraud"),
            ("no-risk", "not_fraud"),
            ("risk-suspected", "unknown"),
        ]
    )

    assert metrics is not None
    assert metrics.total == 3
    assert metrics.confusion_matrix == {
        "no-risk": {"no-risk": 1},
        "risk-suspected": {"risk-suspected": 1},
        "risk": {"risk": 1},
    }
    assert metrics.macro_precision == 1.0
    assert metrics.macro_recall == 1.0
    assert metrics.macro_f1 == 1.0


def test_analyst_agreement_drops_cases_with_unmapped_labels() -> None:
    # None/garbage expected or predicted values (e.g. a case with no
    # classification output yet) must not corrupt the matrix.
    metrics = compute_analyst_agreement_metrics(
        [
            ("risk", "fraud"),
            (None, "fraud"),
            ("risk", None),
        ]
    )

    assert metrics is not None
    assert metrics.total == 1
    assert metrics.confusion_matrix["risk"] == {"risk": 1}


def test_ground_truth_scores_unknown_prediction_as_a_miss() -> None:
    metrics = compute_ground_truth_metrics(
        [
            ("Fraude", "fraud"),
            ("Fraude", "unknown"),
            ("NoFraude", "not_fraud"),
        ]
    )

    assert metrics is not None
    assert metrics.confusion_matrix["Fraude"] == {"Fraude": 1, "unknown": 1}
    # 1 true positive out of 2 actual frauds - the "unknown" never lands on
    # the diagonal, so it drags recall down without special-case logic.
    assert metrics.per_class["Fraude"].recall == 0.5
    assert metrics.per_class["Fraude"].precision == 1.0
    assert metrics.per_class["NoFraude"].recall == 1.0


def test_ground_truth_unknown_never_hurts_precision_of_real_classes() -> None:
    metrics = compute_ground_truth_metrics(
        [
            ("Fraude", "fraud"),
            ("NoFraude", "unknown"),
        ]
    )

    assert metrics is not None
    # NoFraude's lone case was predicted "unknown", not "NoFraude" - it
    # must not count toward Fraude's predicted total either.
    assert metrics.per_class["Fraude"].precision == 1.0
    assert metrics.per_class["NoFraude"].recall == 0.0
