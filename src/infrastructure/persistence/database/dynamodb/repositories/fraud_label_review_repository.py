"""DynamoDB FraudLabelReviewRepository - append-only (table
fraud_label_reviews, see schemas.FRAUD_LABEL_REVIEWS_TABLE). Rows are put
conditioned on not existing and there is deliberately no update/delete."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from boto3.dynamodb.conditions import Key

from src.application.ports.alert_port import Mark
from src.application.ports.fraud_label_review_port import (
    FraudLabelReview,
    FraudLabelReviewChannel,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "fraud_label_reviews"


def review_key(review: FraudLabelReview) -> str:
    """Sort key: UTC review time then id - chronological, and unique even
    for two reviews in the same microsecond."""
    return f"{review.reviewed_at.astimezone(UTC).isoformat()}#{review.id}"


class DynamoFraudLabelReviewRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def create(self, review: FraudLabelReview) -> FraudLabelReview:
        self._table.put_item(
            Item=_to_item(review),
            ConditionExpression="attribute_not_exists(alert_id)",
        )
        return review

    def list_by_alert(self, alert_id: UUID) -> list[FraudLabelReview]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("alert_id").eq(str(alert_id)),
            "ScanIndexForward": True,
        }
        while True:
            response = self._table.query(**kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return [_from_item(item) for item in items]


def _to_item(review: FraudLabelReview) -> dict[str, Any]:
    return {
        "alert_id": str(review.alert_id),
        "review_key": review_key(review),
        "review_id": str(review.id),
        "from_label": review.from_label.value,
        "to_label": review.to_label.value,
        "reviewed_by": review.reviewed_by,
        "reviewed_at": review.reviewed_at.isoformat(),
        "channel": review.channel.value,
        "note": review.note,
    }


def _from_item(item: dict[str, Any]) -> FraudLabelReview:
    return FraudLabelReview(
        id=UUID(item["review_id"]),
        alert_id=UUID(item["alert_id"]),
        from_label=Mark(item["from_label"]),
        to_label=Mark(item["to_label"]),
        reviewed_by=item.get("reviewed_by") or "",
        reviewed_at=datetime.fromisoformat(item["reviewed_at"]),
        channel=FraudLabelReviewChannel(item["channel"]),
        note=item.get("note") or "",
    )
