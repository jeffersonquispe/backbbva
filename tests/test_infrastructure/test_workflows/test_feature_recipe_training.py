"""Versioned recipe parity, category fitting, and artifact compatibility."""

from copy import deepcopy
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from src.application.ports.model_port import ModelRecord, ModelStatus, TrainingConfig
from src.infrastructure.workflows.celery.model_evaluation import train_model_bundle
from src.infrastructure.workflows.celery.model_training import (
    build_feature_frame,
    target_vector,
)


def definition():
    return {
        "schema_version": 1,
        "mappings": {
            "reference_time": "at",
            "history": "history",
            "history_time": "at",
            "timezone": "UTC",
        },
        "recipes": [
            {
                "id": "amount",
                "name": "amount_numeric",
                "source": "current",
                "path": "amount",
                "output_type": "number",
                "steps": [],
            },
            {
                "id": "channel",
                "name": "channel_category",
                "source": "current",
                "path": "channel",
                "output_type": "string",
                "steps": [],
            },
            {
                "id": "count",
                "name": "count_24h",
                "source": "history",
                "window_seconds": 86400,
                "output_type": "number",
                "steps": [{"id": "count-step", "operation": "count"}],
            },
        ],
    }


def sample_rows():
    return [
        {
            "at": f"2026-01-{1+i//24:02d}T{i%24:02d}:00:00Z",
            "label": str(i % 2),
            "amount": i + (i % 2) * 100,
            "channel": ("web" if i % 2 else "app") if i < 120 else "unseen",
            "history": [{"at": "2025-12-31T23:00:00Z"}, {"at": "2030-01-01T00:00:00Z"}],
        }
        for i in range(200)
    ]


def test_recipe_frame_matches_preview_and_preserves_missing():
    from src.domain.models.feature_recipe import evaluate_feature_definition

    rows = sample_rows()[:2]
    rows[1]["channel"] = None
    config = definition()
    frame, _ = build_feature_frame(rows, [], feature_configuration=config)
    for i, row in enumerate(rows):
        preview = evaluate_feature_definition(config, row)["values"]
        assert frame.iloc[i]["amount_numeric"] == preview["amount_numeric"]
        assert frame.iloc[i]["count_24h"] == preview["count_24h"] == 1
    assert pd.isna(frame.iloc[1]["channel_category"])


def test_bundle_persists_snapshot_and_fits_categories_on_training_only():
    rows = sample_rows()
    config = definition()
    record = ModelRecord(
        id=uuid4(),
        tag="recipes",
        description="",
        status=ModelStatus.DRAFT,
        dataset_name="samples",
        target_field="label",
        positive_labels=["1"],
        feature_transforms=[],
        feature_configuration=config,
        training_config=TrainingConfig(
            n_estimators=8, split_strategy="temporal", time_field="at"
        ),
    )
    bundle = train_model_bundle(rows, record)
    assert bundle["cat_categories"]["channel_category"] == ["app", "web"]
    assert bundle["columns"] == ["amount_numeric", "channel_category", "count_24h"]
    assert bundle["feature_configuration"]["schema_version"] == 1
    config["recipes"][0]["path"] = "label"
    assert bundle["feature_configuration"]["recipes"][0]["path"] == "amount"
    with pytest.raises(ValueError):
        train_model_bundle(rows, record)


def test_scoring_real_xgboost_bundle_returns_native_feature_contributions():
    """Keep MCP/worker explanations covered without depending on shap."""
    from src.infrastructure.entrypoint.mcp.scoring import score_row

    rows = sample_rows()
    record = ModelRecord(
        id=uuid4(),
        tag="native-contributions",
        description="",
        status=ModelStatus.DRAFT,
        dataset_name="samples",
        target_field="label",
        positive_labels=["1"],
        feature_transforms=[],
        feature_configuration=definition(),
        training_config=TrainingConfig(
            n_estimators=8, split_strategy="temporal", time_field="at"
        ),
    )

    result = score_row(train_model_bundle(rows, record), rows[0])

    assert 0.0 <= result["score"] <= 1.0
    assert result["top_features"]
    assert {item["feature"] for item in result["top_features"]} <= {
        "amount_numeric",
        "channel_category",
        "count_24h",
    }


def test_scoring_uses_saved_recipe_order_and_categories():
    from src.infrastructure.entrypoint.mcp.scoring import score_row

    class RecordingClassifier:
        def predict_proba(self, frame):
            self.frame = frame.copy()
            return np.array([[0.3, 0.7]])

    class IdentityCalibration:
        def transform(self, values):
            return np.asarray(values)

    classifier = RecordingClassifier()
    bundle = {
        "model": classifier,
        "isotonic": IdentityCalibration(),
        "columns": ["count_24h", "channel_category", "amount_numeric"],
        "cat_categories": {"channel_category": ["app", "web"]},
        "rule_vocab": {},
        "feature_transforms": [],
        "feature_configuration": definition(),
    }
    row = sample_rows()[0]
    row["channel"] = "new"
    result = score_row(bundle, row)
    assert result["score"] == 0.7
    assert list(classifier.frame.columns) == bundle["columns"]
    assert pd.isna(classifier.frame.iloc[0]["channel_category"])
    assert classifier.frame.iloc[0]["count_24h"] == 1
    legacy = deepcopy(bundle)
    legacy.pop("feature_configuration")
    legacy["columns"] = []
    legacy["cat_categories"] = {}
    assert score_row(legacy, row)["score"] == 0.7


def test_target_with_one_class_is_rejected_before_training():
    rows = [{"label": "fraud"}, {"label": "fraud"}]
    with pytest.raises(ValueError, match="dos clases distintas"):
        target_vector(rows, "label", ["fraud"])


def test_explicit_history_filters_match_preview_training_and_scoring():
    from src.application.use_cases.models.feature_engineering import (
        PreviewFeaturesUseCase,
    )
    from src.infrastructure.entrypoint.mcp.scoring import score_row

    config = definition()
    config["schema_version"] = 2
    config["mappings"] = {"history": "history", "timezone": "UTC"}
    history = config["recipes"][2]
    history.pop("window_seconds")
    history["steps"].insert(
        0,
        {
            "id": "dates",
            "operation": "filter",
            "conditions": [
                {
                    "path": "at",
                    "operator": "lt",
                    "value_type": "datetime",
                    "current_path": "at",
                },
                {
                    "path": "at",
                    "operator": "gte",
                    "value_type": "datetime",
                    "current_path": "at",
                    "offset_seconds": -86400,
                },
            ],
        },
    )
    rows = sample_rows()[:2]
    preview = PreviewFeaturesUseCase().execute(config, rows, "label")
    frame, _ = build_feature_frame(rows, [], feature_configuration=config)
    for i in range(2):
        assert (
            frame.iloc[i]["count_24h"] == preview["rows"][i]["values"]["count_24h"] == 1
        )

    class RecordingClassifier:
        def predict_proba(self, frame):
            self.frame = frame.copy()
            return np.array([[0.3, 0.7]])

    class IdentityCalibration:
        def transform(self, values):
            return np.asarray(values)

    classifier = RecordingClassifier()
    bundle = {
        "model": classifier,
        "isotonic": IdentityCalibration(),
        "columns": ["count_24h", "amount_numeric", "channel_category"],
        "cat_categories": {"channel_category": ["app", "web"]},
        "rule_vocab": {},
        "feature_transforms": [],
        "feature_configuration": config,
    }
    assert score_row(bundle, rows[0])["score"] == 0.7
    assert (
        classifier.frame.iloc[0]["count_24h"]
        == preview["rows"][0]["values"]["count_24h"]
    )
