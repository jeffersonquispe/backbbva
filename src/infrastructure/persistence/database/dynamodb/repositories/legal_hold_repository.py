"""Legal holds on alerts (LegalHoldRepository); one row per alert."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from botocore.exceptions import ClientError

from src.application.ports.legal_hold_port import LegalHold, LegalHoldRepository
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "legal_holds"
_BATCH_GET = 100


class DynamoLegalHoldRepository(LegalHoldRepository):
    def __init__(
        self, table: Any | None = None, *, resource: Any | None = None
    ) -> None:
        self._resource = resource if resource is not None else get_dynamodb_resource()
        self._table = table if table is not None else self._resource.Table(TABLE_NAME)
        self._table_name = self._table.name

    def place(self, hold: LegalHold) -> bool:
        item: dict[str, Any] = {
            "alert_id": hold.alert_id,
            "reason": hold.reason,
            "placed_by": hold.placed_by,
            "placed_at": hold.placed_at.isoformat(),
            "active": "Y",
        }
        if hold.case_reference:
            item["case_reference"] = hold.case_reference
        try:
            # A released row may be replaced by a new hold; an active one may not.
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(alert_id) OR attribute_not_exists(active)",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def release(
        self,
        alert_id: str,
        *,
        released_by: str,
        release_reason: str,
        released_at: datetime,
    ) -> LegalHold | None:
        try:
            response = self._table.update_item(
                Key={"alert_id": alert_id},
                UpdateExpression=(
                    "SET released_at = :at, released_by = :by, release_reason = :why "
                    "REMOVE active"
                ),
                ConditionExpression="attribute_exists(active)",
                ExpressionAttributeValues={
                    ":at": released_at.isoformat(),
                    ":by": released_by,
                    ":why": release_reason,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        return _hold(response["Attributes"])

    def get(self, alert_id: str) -> LegalHold | None:
        item = self._table.get_item(
            Key={"alert_id": alert_id}, ConsistentRead=True
        ).get("Item")
        return _hold(item) if item else None

    def list_active(self, limit: int = 100) -> list[LegalHold]:
        # The table only holds alerts someone deliberately froze, so a filtered
        # scan stays small (unlike the alerts table, which is never scanned).
        holds: list[LegalHold] = []
        kwargs: dict[str, Any] = {
            "FilterExpression": "attribute_exists(active)",
            "ConsistentRead": True,
        }
        while len(holds) < limit:
            page = self._table.scan(**kwargs)
            holds.extend(_hold(item) for item in page.get("Items", []))
            last = page.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        holds.sort(key=lambda hold: hold.placed_at, reverse=True)
        return holds[:limit]

    def active_ids(self, alert_ids: Sequence[str]) -> set[str]:
        found: set[str] = set()
        unique = list(dict.fromkeys(alert_ids))
        for start in range(0, len(unique), _BATCH_GET):
            keys = [{"alert_id": value} for value in unique[start : start + _BATCH_GET]]
            pending = {self._table_name: {"Keys": keys, "ConsistentRead": True}}
            while pending:
                response = self._resource.batch_get_item(RequestItems=pending)
                for item in response.get("Responses", {}).get(self._table_name, []):
                    if "active" in item:
                        found.add(item["alert_id"])
                pending = response.get("UnprocessedKeys") or {}
        return found


def _hold(item: dict[str, Any]) -> LegalHold:
    return LegalHold(
        alert_id=item["alert_id"],
        reason=item["reason"],
        case_reference=item.get("case_reference"),
        placed_by=item["placed_by"],
        placed_at=datetime.fromisoformat(item["placed_at"]),
        released_at=(
            datetime.fromisoformat(item["released_at"])
            if item.get("released_at")
            else None
        ),
        released_by=item.get("released_by"),
        release_reason=item.get("release_reason"),
    )
