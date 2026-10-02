"""DynamoDB AlertReasoningEvaluationRepository (D6): one LLM-judge verdict per
alert in table alert_reasoning_evaluations (pk alert_id). create() is a
conditional put - the first verdict stored for an alert wins."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "alert_reasoning_evaluations"


class DynamoAlertReasoningEvaluationRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def create(
        self, record: AlertReasoningEvaluationRecord
    ) -> AlertReasoningEvaluationRecord:
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


def _to_item(record: AlertReasoningEvaluationRecord) -> dict[str, Any]:
    return {
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
    )
