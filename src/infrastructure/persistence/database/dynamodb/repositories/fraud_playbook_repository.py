from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.application.ports.fraud_playbook_port import (
    FraudPlaybookRecord,
    FraudPlaybookRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

PLAYBOOKS_TABLE_NAME = "fraud_playbooks"


class DynamoFraudPlaybookRepository(FraudPlaybookRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(PLAYBOOKS_TABLE_NAME)

    def create(self, playbook: FraudPlaybookRecord) -> FraudPlaybookRecord:
        self._table.put_item(Item=_to_item(playbook))
        return playbook

    def get(self, classification: str) -> FraudPlaybookRecord | None:
        response = self._table.get_item(Key={"classification": classification})
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)

    def update(
        self,
        classification: str,
        *,
        title: str | None = None,
        steps: list[str] | None = None,
    ) -> FraudPlaybookRecord | None:
        current = self.get(classification)
        if current is None:
            return None
        updated = FraudPlaybookRecord(
            classification=current.classification,
            title=title if title is not None else current.title,
            steps=steps if steps is not None else current.steps,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def list(self) -> list[FraudPlaybookRecord]:
        response = self._table.scan()
        return [_from_item(item) for item in response.get("Items", [])]


def _to_item(playbook: FraudPlaybookRecord) -> dict[str, Any]:
    return {
        "classification": playbook.classification,
        "title": playbook.title,
        "steps": playbook.steps,
        "created_at": playbook.created_at.isoformat(),
        "updated_at": playbook.updated_at.isoformat(),
    }


def _from_item(item: dict[str, Any]) -> FraudPlaybookRecord:
    return FraudPlaybookRecord(
        classification=item["classification"],
        title=item["title"],
        steps=list(item.get("steps") or []),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )
