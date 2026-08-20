from __future__ import annotations

from collections import Counter

from src.application.dtos.test_run_dtos import ClassificationMetrics, ClassMetrics
from src.application.use_cases.test_runs.dataset_sampling import MARCACION_CLASSES

# The model's is_fraud value has no 1:1 vocabulary match with either
# ground-truth column, so each comparison gets its own mapping:
#
# - vs. the analyst's marcacion_final: "unknown" lands on risk-suspected,
#   since both mean "not confident enough to call it either way" - gives a
#   full 3x3 matrix, no case excluded.
# - vs. the real matured outcome (tipo, binary Fraude/NoFraude): "unknown"
#   has no natural side to land on, so it's kept as a predicted-only bucket
#   that's never on the diagonal - it always counts against that case's
#   recall (an "unknown" is scored as a miss), without special-casing the
#   metric math below.
_ANALYST_LABELS = MARCACION_CLASSES
_IS_FRAUD_TO_ANALYST = {
    "fraud": "risk",
    "unknown": "risk-suspected",
    "not_fraud": "no-risk",
}

_GROUND_TRUTH_LABELS = ("Fraude", "NoFraude")
_IS_FRAUD_TO_GROUND_TRUTH = {
    "fraud": "Fraude",
    "not_fraud": "NoFraude",
    "unknown": "unknown",
}


def _compute(
    pairs: list[tuple[str, str]],
    expected_labels: tuple[str, ...],
) -> ClassificationMetrics | None:
    if not pairs:
        return None

    confusion: dict[str, Counter[str]] = {label: Counter() for label in expected_labels}
    predicted_totals: Counter[str] = Counter()
    for expected, predicted in pairs:
        confusion[expected][predicted] += 1
        predicted_totals[predicted] += 1

    per_class: dict[str, ClassMetrics] = {}
    for label in expected_labels:
        support = sum(confusion[label].values())
        true_positive = confusion[label][label]
        predicted_as_label = predicted_totals[label]
        precision = true_positive / predicted_as_label if predicted_as_label else 0.0
        recall = true_positive / support if support else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        per_class[label] = ClassMetrics(
            precision=precision, recall=recall, f1=f1, support=support
        )

    class_count = len(expected_labels)
    return ClassificationMetrics(
        per_class=per_class,
        macro_precision=sum(c.precision for c in per_class.values()) / class_count,
        macro_recall=sum(c.recall for c in per_class.values()) / class_count,
        macro_f1=sum(c.f1 for c in per_class.values()) / class_count,
        confusion_matrix={label: dict(counts) for label, counts in confusion.items()},
        total=len(pairs),
    )


def compute_analyst_agreement_metrics(
    cases: list[tuple[str | None, str | None]],
) -> ClassificationMetrics | None:
    """cases = [(expected_classification, is_fraud), ...] straight off each
    case's final classification attempt output."""
    pairs = [
        (expected, _IS_FRAUD_TO_ANALYST[is_fraud])
        for expected, is_fraud in cases
        if expected in _ANALYST_LABELS and is_fraud in _IS_FRAUD_TO_ANALYST
    ]
    return _compute(pairs, _ANALYST_LABELS)


def compute_ground_truth_metrics(
    cases: list[tuple[str | None, str | None]],
) -> ClassificationMetrics | None:
    """cases = [(ground_truth_tipo, is_fraud), ...] straight off each case's
    final classification attempt output."""
    pairs = [
        (expected, _IS_FRAUD_TO_GROUND_TRUTH[is_fraud])
        for expected, is_fraud in cases
        if expected in _GROUND_TRUTH_LABELS and is_fraud in _IS_FRAUD_TO_GROUND_TRUTH
    ]
    return _compute(pairs, _GROUND_TRUTH_LABELS)
