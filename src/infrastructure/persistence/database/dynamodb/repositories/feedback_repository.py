from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from src.application.ports.feedback_port import FeedbackRecord, FeedbackRepository
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

FEEDBACK_TABLE_NAME = "feedback"


class DynamoFeedbackRepository(FeedbackRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(FEEDBACK_TABLE_NAME)

    def create(self, feedback: FeedbackRecord) -> FeedbackRecord:
        self._table.put_item(Item=_to_item(feedback))
        return feedback

    def get(self, feedback_id: UUID) -> FeedbackRecord | None:
        response = self._table.get_item(Key={"id": str(feedback_id)})
        item = response.get("Item")
        return _from_item(item) if item else None

    def list(
        self,
        configuration_id: str | None = None,
        version: int | None = None,
    ) -> list[FeedbackRecord]:
        # Scan + filter in Python, same pattern as this codebase's other
        # low-write-volume flat CRUD repos (e.g. DynamoChannelLibraryRepository)
        # - no GSI, feedback entries aren't expected at a volume that needs one.
        response = self._table.scan()
        records = [_from_item(item) for item in response.get("Items", [])]
        if configuration_id is not None:
            records = [r for r in records if r.configuration_id == configuration_id]
        if version is not None:
            records = [r for r in records if r.version == version]
        return records


def _to_item(feedback: FeedbackRecord) -> dict[str, Any]:
    return {
        "id": str(feedback.id),
        "configuration_id": feedback.configuration_id,
        "version": feedback.version,
        "alert_id": str(feedback.alert_id),
        "justification": feedback.justification,
        "dataset_name": feedback.dataset_name,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
        "created_by": feedback.created_by,
    }


def _from_item(item: dict[str, Any]) -> FeedbackRecord:
    created_at = item.get("created_at")
    return FeedbackRecord(
        id=UUID(item["id"]),
        configuration_id=item["configuration_id"],
        version=int(item["version"]),
        alert_id=UUID(item["alert_id"]),
        justification=item["justification"],
        dataset_name=item.get("dataset_name"),
        created_at=datetime.fromisoformat(created_at) if created_at else None,
        created_by=item.get("created_by"),
    )
