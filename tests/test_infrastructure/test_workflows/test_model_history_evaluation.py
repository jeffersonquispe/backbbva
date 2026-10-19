from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest

from src.application.ports.model_port import (
    FieldTransform,
    FieldTransformKind,
    HistoricalFeature,
    ModelRecord,
    ModelStatus,
    TrainingConfig,
)
from src.infrastructure.workflows.celery.historical_features import build_history_frame
from src.infrastructure.workflows.celery.model_evaluation import (
    split_indices,
    train_model_bundle,
)
from src.infrastructure.workflows.celery.model_training import build_feature_frame


def test_history_cutoff_missing_events_and_timezone():
    rows = [
        {
            "at": "2026-01-02 12:00:00",
            "history": [
                '{"eventtime":"2026-01-02T17:00:00Z","amount_value":999}',
                {"eventtime": "2026-01-02T18:00:00Z", "amount_value": 888},
                {"eventtime": "2026-01-02T16:00:00Z", "amount_value": 20},
                {"eventtime": "2026-01-01T17:00:00Z", "amount_value": 40},
                {"eventtime": "2026-01-02T15:00:00Z"},
                {"eventtime": "2025-12-01T00:00:00Z", "amount_value": 777},
            ],
        }
    ]
    count = HistoricalFeature(name="count", field="history", reference_field="at")
    median = replace(count, name="median", operation="median")
    frame = build_history_frame(rows, [count, median], "America/Bogota")
    assert frame.iloc[0].tolist() == [3, 30]
    assert (
        build_history_frame(
            [{**rows[0], "history": []}], [count, median], "America/Bogota"
        ).iloc[0, 0]
        == 0
    )
    assert np.isnan(
        build_history_frame(
            [{**rows[0], "history": None}], [count], "America/Bogota"
        ).iloc[0, 0]
    )
    with pytest.raises(ValueError, match="JSON"):
        build_history_frame(
            [{**rows[0], "history": "not-json"}], [count], "America/Bogota"
        )


def test_history_filters_and_zero_denominator():
    recipe = HistoricalFeature(
        name="ratio",
        field="history",
        reference_field="at",
        operation="sum",
        compare_field="amount",
        filter_field="canal",
        filter_value="App",
    )
    row = {
        "at": "2026-01-02",
        "amount": 100,
        "history": [
            {"eventtime": "2026-01-01T23:00:00", "canal": "App", "amount_value": 0},
            {"eventtime": "2026-01-01T23:00:00", "canal": "Web", "amount_value": 100},
        ],
    }
    assert np.isnan(build_history_frame([row], [recipe], "UTC").iloc[0, 0])


def rows_and_record():
    rows = [
        {
            "at": f"2026-01-{1+i//24:02d}T{i%24:02d}:00:00Z",
            "label": "risk" if i % 2 else "safe",
            "amount": i % 2 * 100 + i,
            "category": "a" if i % 2 else "b",
            "rules": "[base]" if i < 120 else "[test_only]",
            "history": [{"eventtime": "2025-12-31T23:00:00Z", "amount_value": i}],
        }
        for i in range(200)
    ]
    record = ModelRecord(
        id=uuid4(),
        tag="test",
        description="",
        status=ModelStatus.DRAFT,
        dataset_name="test",
        target_field="label",
        positive_labels=["risk"],
        feature_transforms=[
            FieldTransform(field="amount", kind=FieldTransformKind.NUMERIC),
            FieldTransform(field="rules", kind=FieldTransformKind.RULE_MULTIHOT),
        ],
        historical_features=[
            HistoricalFeature(
                name="count", field="history", reference_field="at", window_hours=2160
            )
        ],
        training_config=TrainingConfig(
            n_estimators=8, split_strategy="temporal", time_field="at"
        ),
    )
    return rows, record


def test_training_uses_disjoint_data_persists_recipe_and_metrics():
    rows, record = rows_and_record()
    bundle = train_model_bundle(rows, record)
    assert bundle["rule_vocab"]["rules"] == ["base"]
    assert bundle["model"].get_params()["n_estimators"] == 8
    assert bundle["training_report"]["partitions"] == {
        "training": {"rows": 120, "positive": 60},
        "validation": {"rows": 30, "positive": 15},
        "calibration": {"rows": 20, "positive": 10},
        "test": {"rows": 30, "positive": 15},
    }
    assert bundle["metrics"]["tp"] + bundle["metrics"]["fn"] == 15
    assert (
        bundle["metrics"]["tp"]
        + bundle["metrics"]["fp"]
        + bundle["metrics"]["fn"]
        + bundle["metrics"]["tn"]
        == 30
    )
    assert all(
        0 <= bundle["metrics"][key] <= 1
        for key in ("roc_auc", "average_precision", "brier_score", "f1")
    )
    scored, vocab = build_feature_frame(
        [rows[-1]],
        bundle["feature_transforms"],
        bundle["rule_vocab"],
        bundle["historical_features"],
        bundle["training_config"]["timezone"],
    )
    assert scored.columns.tolist() == bundle["columns"]
    assert scored["history__count"].iloc[0] == 1
    assert vocab == bundle["rule_vocab"]


def test_temporal_split_does_not_split_equal_timestamps():
    rows, record = rows_and_record()
    for i in range(115, 125):
        rows[i]["at"] = rows[115]["at"]
    y = np.array([i % 2 for i in range(200)])
    parts = split_indices(rows, y, record.training_config)
    assert max(parts["training"]) == 114
    assert min(parts["validation"]) == 115
    assert len(set().union(*(set(p) for p in parts.values()))) == 200


def test_target_leakage_and_empty_classes_rejected():
    rows, record = rows_and_record()
    record.feature_transforms.append(
        FieldTransform(field="label", kind=FieldTransformKind.CATEGORICAL)
    )
    with pytest.raises(ValueError, match="objetivo"):
        train_model_bundle(rows, record)
    with pytest.raises(ValueError, match="ambas clases"):
        split_indices(rows, np.zeros(200), record.training_config)


def test_workflow_persists_bundle_and_report():
    from io import BytesIO

    import joblib

    from src.infrastructure.workflows.celery.model_training import run_model_training

    rows, record = rows_and_record()

    class InMemoryModels:
        def get(self, model_id):
            return record

        def update(self, model):
            pass

    class InMemoryDatasets:
        def get_rows(self, dataset_name):
            return rows

    class RecordingOperations:
        def __init__(self):
            self.updates = []

        def update(self, *args, **kwargs):
            self.updates.append(kwargs)

    class RecordingStorage:
        def __init__(self):
            self.puts = []

        def put_bytes(self, *args, **kwargs):
            self.puts.append(kwargs)

    models, datasets = InMemoryModels(), InMemoryDatasets()
    operations, storage = RecordingOperations(), RecordingStorage()
    result = run_model_training(
        str(record.id),
        str(uuid4()),
        model_repository=models,
        async_operation_repository=operations,
        dataset_repository=datasets,
        model_object_storage=storage,
    )
    artifact = joblib.load(BytesIO(storage.puts[-1]["content"]))
    assert result["status"] == "ok"
    assert record.status == ModelStatus.READY
    assert record.training_report == artifact["training_report"]
    assert record.historical_features == artifact["historical_features"]
    assert operations.updates[-1]["status"] == "SUCCEEDED"
