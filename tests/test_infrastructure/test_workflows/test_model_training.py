from __future__ import annotations

import numpy as np
import pytest

from src.application.ports.model_port import FieldTransform, FieldTransformKind
from src.infrastructure.workflows.celery.model_evaluation import split_indices
from src.infrastructure.workflows.celery.model_training import (
    build_feature_frame,
    target_vector,
    train_xgboost_model,
)


def _synthetic_rows(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        positive = i % 2 == 0
        rows.append(
            {
                "channel": "web" if positive else "mobile",
                "amount_value": 1000 + i if positive else 10 + i,
                "fecha_transaccion": (
                    f"2026-01-{(i % 27) + 1:02d} {(9 + i % 12):02d}:00:00"
                ),
                "fecha_alta": "2020-01-01 00:00:00",
                "triggered_rules": (
                    "[CUSTOMER - dg_risknewpayee, CARD - TJ_x]" if positive else "[]"
                ),
                "marcacion_final": "risk" if positive else "no-risk",
            }
        )
    return rows


TRANSFORMS = [
    FieldTransform(field="channel", kind=FieldTransformKind.CATEGORICAL),
    FieldTransform(field="amount_value", kind=FieldTransformKind.NUMERIC),
    FieldTransform(
        field="fecha_transaccion",
        kind=FieldTransformKind.DATE_DERIVED,
        reference_field="fecha_alta",
    ),
    FieldTransform(
        field="triggered_rules", kind=FieldTransformKind.RULE_MULTIHOT, top_n=5
    ),
]


def test_build_feature_frame_applies_every_transform_kind() -> None:
    rows = _synthetic_rows(20)

    X, rule_vocab = build_feature_frame(rows, TRANSFORMS)

    assert str(X["channel"].dtype) == "category"
    assert X["amount_value"].dtype.kind in "if"
    assert "fecha_transaccion__hour" in X.columns
    assert "fecha_transaccion__days_since_fecha_alta" in X.columns
    assert "triggered_rules__n_tokens" in X.columns
    assert rule_vocab["triggered_rules"]  # fit a non-empty vocabulary


def test_build_feature_frame_reuses_fixed_rule_vocab_at_scoring_time() -> None:
    rows = _synthetic_rows(20)
    _, rule_vocab = build_feature_frame(rows, TRANSFORMS)

    # scoring one row later must reproduce the same multi-hot columns
    X_one, reused_vocab = build_feature_frame(
        [rows[0]], TRANSFORMS, rule_vocab=rule_vocab
    )

    assert reused_vocab == rule_vocab
    assert all(
        f"triggered_rules__{token}"[:60] in X_one.columns
        for token in rule_vocab["triggered_rules"]
    )


def test_feature_and_target_extraction_support_dotted_catalog_fields() -> None:
    rows = [
        {"biocatch": {"score": "258"}, "review": {"status": "risk"}},
        {"biocatch": {"score": "12"}, "review": {"status": "no-risk"}},
    ]

    X, _ = build_feature_frame(
        rows,
        [FieldTransform(field="biocatch.score", kind=FieldTransformKind.NUMERIC)],
    )
    y = target_vector(rows, "review.status", ["risk"])

    assert X["biocatch.score"].tolist() == [258, 12]
    assert y.tolist() == [1, 0]


def test_train_xgboost_model_fits_and_reports_metrics() -> None:
    rows = _synthetic_rows(40)
    X, _ = build_feature_frame(rows, TRANSFORMS)
    y = target_vector(rows, "marcacion_final", ["risk"])

    model, isotonic, metrics = train_xgboost_model(X, y)

    assert 0.0 <= metrics["roc_auc"] <= 1.0
    assert metrics["n_samples"] == 40.0
    proba = model.predict_proba(X)[:, 1]
    calibrated = isotonic.transform(proba)
    assert np.all((calibrated >= 0.0) & (calibrated <= 1.0))


def test_mature_snapshot_uses_only_non_final_partitions() -> None:
    partition_names = ("training", "validation", "test")
    rows = [
        {
            "__aria_partition": partition_names[index // 4],
            "feature": index,
        }
        for index in range(12)
    ]
    labels = np.asarray([index % 2 for index in range(12)])

    partitions = split_indices(rows, labels, config=None)

    assert partitions["training"].tolist() == [0, 1, 2, 3]
    assert partitions["validation"].tolist() == [4, 5, 6, 7]
    assert partitions["calibration"].tolist() == [8, 9, 10, 11]
    assert set(partitions) == {"training", "validation", "calibration"}


def test_mature_snapshot_rejects_reserved_final_partition() -> None:
    rows = [
        {"__aria_partition": partition, "feature": index}
        for index, partition in enumerate(
            ["training"] * 4 + ["validation"] * 4 + ["test"] * 4 + ["final"] * 4
        )
    ]
    labels = np.asarray([index % 2 for index in range(16)])

    with pytest.raises(ValueError, match="reservada para evaluación global"):
        split_indices(rows, labels, config=None)
