"""DynamoDB AlertReasoningEvaluationRepository (D6): one LLM-judge verdict per
alert in table alert_reasoning_evaluations (pk alert_id). create() is a
conditional put - the first verdict stored for an alert wins."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "alert_reasoning_evaluations"
DAYS_TABLE_NAME = "alert_reasoning_evaluation_days"
_BATCH_GET = 100


class DynamoAlertReasoningEvaluationRepository:
    def __init__(self, table: Any | None = None, days_table: Any | None = None) -> None:
        resource = (
            get_dynamodb_resource() if table is None or days_table is None else None
        )
        self._table = table if table is not None else resource.Table(TABLE_NAME)
        self._days = (
            days_table if days_table is not None else resource.Table(DAYS_TABLE_NAME)
        )
        self._resource = resource

    def create(
        self, record: AlertReasoningEvaluationRecord
    ) -> AlertReasoningEvaluationRecord:
        # The day entry goes first: a crash before the verdict leaves an entry
        # that points at nothing (skipped when listing), never a verdict that
        # can't be listed.
        self._days.put_item(
            Item={
                "evaluated_day": _evaluated_day(record),
                "alert_id": str(record.alert_id),
            }
        )
        try:
            self._table.put_item(
                Item=_to_item(record),
                ConditionExpression="attribute_not_exists(alert_id)",
            )
            return record
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        existing = self.get(record.alert_id)
        return existing if existing is not None else record

    def get(self, alert_id: UUID) -> AlertReasoningEvaluationRecord | None:
        item = self._table.get_item(
            Key={"alert_id": str(alert_id)}, ConsistentRead=True
        ).get("Item")
        return _from_item(item) if item else None

    def list_between(
        self, from_day: date, to_day: date, *, limit: int
    ) -> list[AlertReasoningEvaluationRecord]:
        records: list[AlertReasoningEvaluationRecord] = []
        day = to_day
        while day >= from_day and len(records) < limit:
            records.extend(self._day_records(day.isoformat()))
            day -= timedelta(days=1)
        records.sort(key=lambda r: r.evaluated_at, reverse=True)
        return records[:limit]

    def _day_records(self, day: str) -> list[AlertReasoningEvaluationRecord]:
        alert_ids: list[str] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("evaluated_day").eq(day)
        }
        while True:
            page = self._days.query(**kwargs)
            alert_ids.extend(item["alert_id"] for item in page.get("Items", []))
            last = page.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        records: list[AlertReasoningEvaluationRecord] = []
        for start in range(0, len(alert_ids), _BATCH_GET):
            chunk = alert_ids[start : start + _BATCH_GET]
            for item in self._load(chunk):
                record = _from_item(item)
                # A retry that judged on another day left its first entry
                # behind: only the day of the stored verdict counts.
                if _evaluated_day(record) == day:
                    records.append(record)
        return records

    def _load(self, alert_ids: list[str]) -> list[dict[str, Any]]:
        if self._resource is not None:
            name = self._table.name
            pending = {
                name: {
                    "Keys": [{"alert_id": a} for a in alert_ids],
                    "ConsistentRead": True,
                }
            }
            items: list[dict[str, Any]] = []
            while pending:
                response = self._resource.batch_get_item(RequestItems=pending)
                items.extend(response.get("Responses", {}).get(name, []))
                pending = response.get("UnprocessedKeys") or {}
            return items
        # Injected tables (tests): one read per alert.
        found = (
            self._table.get_item(Key={"alert_id": a}, ConsistentRead=True).get("Item")
            for a in alert_ids
        )
        return [item for item in found if item]


def _evaluated_day(record: AlertReasoningEvaluationRecord) -> str:
    zone = ZoneInfo(genai_config.OPERATIONS_TIMEZONE)
    return record.evaluated_at.astimezone(zone).date().isoformat()


def _to_item(record: AlertReasoningEvaluationRecord) -> dict[str, Any]:
    return {
        "prompt_version": record.prompt_version,
        # Stored as JSON text: DynamoDB would turn the nested booleans and
        # notes into maps the rest of the code never needs to query.
        "step_verdicts": json.dumps(record.step_verdicts, ensure_ascii=False),
        "attempts": record.attempts,
        "criteria_verdicts": json.dumps(record.criteria_verdicts, ensure_ascii=False),
        "duration_ms": record.duration_ms,
        "alert_id": str(record.alert_id),
        "workflow_execution_id": str(record.workflow_execution_id),
        "status": record.status.value,
        "hallucination": record.hallucination,
        "data_use_correct": record.data_use_correct,
        "rationale": record.rationale,
        "judge_model": record.judge_model,
        "evaluated_at": record.evaluated_at.isoformat(),
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
    }


def _optional_bool(value: Any) -> bool | None:
    return bool(value) if value is not None else None


def _from_item(item: dict[str, Any]) -> AlertReasoningEvaluationRecord:
    return AlertReasoningEvaluationRecord(
        alert_id=UUID(item["alert_id"]),
        workflow_execution_id=UUID(item["workflow_execution_id"]),
        status=ReasoningEvaluationStatus(item.get("status", "invalid")),
        hallucination=_optional_bool(item.get("hallucination")),
        data_use_correct=_optional_bool(item.get("data_use_correct")),
        rationale=str(item.get("rationale") or ""),
        judge_model=str(item.get("judge_model") or ""),
        evaluated_at=datetime.fromisoformat(item["evaluated_at"]),
        input_tokens=int(item.get("input_tokens") or 0),
        output_tokens=int(item.get("output_tokens") or 0),
        prompt_version=str(item.get("prompt_version") or "v1"),
        step_verdicts=_json_dict(item.get("step_verdicts")),
        attempts=int(item.get("attempts") or 1),
        criteria_verdicts=_json_dict(item.get("criteria_verdicts")),
        duration_ms=int(item.get("duration_ms") or 0),
    )


def _json_dict(raw: Any) -> dict[str, dict[str, object]]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
