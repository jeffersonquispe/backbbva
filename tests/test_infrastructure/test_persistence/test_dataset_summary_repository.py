from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSummaryRecord,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_summary_repository import (
    _from_item,
    _to_item,
)


def test_fraud_marking_analysis_serializes_float_metrics_for_dynamodb() -> None:
    record = DatasetSummaryRecord(
        dataset_name="dataset",
        status=DatasetAnalysisStatus.READY,
        total_rows=1,
        fraud_marking_analysis={
            "maturation": {"avg_days": 1.25, "p95_days": 2.5},
        },
        updated_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )

    item = _to_item(record)

    assert item["fraud_marking_analysis"]["maturation"]["avg_days"] == Decimal("1.25")
    restored = _from_item(item)
    assert restored.fraud_marking_analysis == record.fraud_marking_analysis


def test_legacy_hour_based_maturation_is_returned_in_days() -> None:
    record = DatasetSummaryRecord(
        dataset_name="dataset",
        status=DatasetAnalysisStatus.READY,
        total_rows=1,
        fraud_marking_analysis={"maturation": {"avg_hours": 36.0}},
    )

    restored = _from_item(_to_item(record))

    assert restored.fraud_marking_analysis == {
        "maturation": {
            "avg_days": 1.5,
            "min_days": None,
            "max_days": None,
            "p95_days": None,
        }
    }
