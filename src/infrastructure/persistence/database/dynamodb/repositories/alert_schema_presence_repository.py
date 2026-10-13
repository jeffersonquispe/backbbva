from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from src.application.ports.alert_schema_port import (
    AlertSchemaPresenceField,
    AlertSchemaPresenceReport,
    AlertSchemaPresenceReportRepository,
    AlertSchemaUnknownLocation,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

TABLE_NAME = "alert_schema_presence_reports"


class DynamoAlertSchemaPresenceReportRepository(AlertSchemaPresenceReportRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def save(self, report: AlertSchemaPresenceReport) -> AlertSchemaPresenceReport:
        self._table.put_item(Item=to_dynamodb(_to_item(report)))
        return report

    def get(self, report_day: date) -> AlertSchemaPresenceReport | None:
        item = self._table.get_item(Key={"report_day": report_day.isoformat()}).get(
            "Item"
        )
        return _from_item(item) if item else None

    def get_latest(self) -> AlertSchemaPresenceReport | None:
        result = self._table.scan()
        reports = [_from_item(item) for item in result.get("Items", [])]
        return max(reports, key=lambda item: item.report_day, default=None)

    def list_before(
        self, report_day: date, limit: int = 30
    ) -> list[AlertSchemaPresenceReport]:
        result = self._table.scan()
        reports = [
            _from_item(item)
            for item in result.get("Items", [])
            if item.get("report_day", "") < report_day.isoformat()
        ]
        return sorted(reports, key=lambda item: item.report_day, reverse=True)[:limit]


def _to_item(report: AlertSchemaPresenceReport) -> dict[str, Any]:
    item = asdict(report)
    item["report_day"] = report.report_day.isoformat()
    item["generated_at"] = report.generated_at.isoformat()
    for field in item["fields"]:
        if field["last_seen"] is not None:
            field["last_seen"] = field["last_seen"].isoformat()
    return item


def _from_item(item: dict[str, Any]) -> AlertSchemaPresenceReport:
    value = from_dynamodb(item)
    return AlertSchemaPresenceReport(
        report_day=date.fromisoformat(value["report_day"]),
        generated_at=datetime.fromisoformat(value["generated_at"]),
        schema_version=int(value["schema_version"]),
        alert_count=int(value.get("alert_count", 0)),
        fields=[
            AlertSchemaPresenceField(
                **{
                    **field,
                    "last_seen": datetime.fromisoformat(field["last_seen"])
                    if field.get("last_seen")
                    else None,
                }
            )
            for field in value.get("fields", [])
        ],
        unknown_locations=[
            AlertSchemaUnknownLocation(**location)
            for location in value.get("unknown_locations", [])
        ],
    )
