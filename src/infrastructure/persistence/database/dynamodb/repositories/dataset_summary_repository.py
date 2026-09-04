from __future__ import annotations

from datetime import datetime
from typing import Any

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

DATASET_SUMMARIES_TABLE_NAME = "dataset_summaries"


class DynamoDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(DATASET_SUMMARIES_TABLE_NAME)

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._table.put_item(Item=_to_item(summary))
        return summary

    def delete(self, dataset_name: str) -> None:
        self._table.delete_item(Key={"dataset_name": dataset_name})

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        response = self._table.get_item(Key={"dataset_name": dataset_name})
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)


def _to_item(summary: DatasetSummaryRecord) -> dict[str, Any]:
    return {
        "dataset_name": summary.dataset_name,
        "status": summary.status.value,
        "total_rows": summary.total_rows,
        "field_distributions": summary.field_distributions,
        "available_fields": summary.available_fields,
        "uploaded_at": summary.uploaded_at.isoformat() if summary.uploaded_at else None,
        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
        "error": summary.error,
    }


def _from_item(item: dict[str, Any]) -> DatasetSummaryRecord:
    uploaded_at = item.get("uploaded_at")
    updated_at = item.get("updated_at")
    return DatasetSummaryRecord(
        dataset_name=item["dataset_name"],
        status=DatasetAnalysisStatus(item["status"]),
        total_rows=int(item.get("total_rows") or 0),
        field_distributions={
            field_name: {value: int(count) for value, count in counts.items()}
            for field_name, counts in (item.get("field_distributions") or {}).items()
        },
        available_fields=list(item.get("available_fields") or []),
        uploaded_at=datetime.fromisoformat(uploaded_at) if uploaded_at else None,
        updated_at=datetime.fromisoformat(updated_at) if updated_at else None,
        error=item.get("error"),
    )
