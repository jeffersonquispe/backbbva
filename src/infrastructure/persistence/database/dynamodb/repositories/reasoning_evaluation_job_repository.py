"""DynamoDB ReasoningEvaluationJobRepository: the evaluator's own job state,
one row per alert in alert_reasoning_evaluation_jobs (pk alert_id, StatusIdx on
status + queued_at for the recovery sweep)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.reasoning_evaluation_job_port import (
    ReasoningEvaluationJob,
    ReasoningEvaluationJobRepository,
    ReasoningEvaluationJobStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "alert_reasoning_evaluation_jobs"
STATUS_INDEX = "StatusIdx"


class DynamoReasoningEvaluationJobRepository(ReasoningEvaluationJobRepository):
    def __init__(self, table: Any | None = None) -> None:
        self._table = (
            table if table is not None else get_dynamodb_resource().Table(TABLE_NAME)
        )

    def create_if_absent(self, job: ReasoningEvaluationJob) -> bool:
        try:
            self._table.put_item(
                Item=_to_item(job), ConditionExpression="attribute_not_exists(alert_id)"
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def requeue(self, job: ReasoningEvaluationJob) -> bool:
        try:
            self._table.put_item(
                Item=_to_item(job),
                ConditionExpression="#s IN (:failed, :invalid)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":failed": ReasoningEvaluationJobStatus.FAILED.value,
                    ":invalid": ReasoningEvaluationJobStatus.INVALID.value,
                },
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def save(self, job: ReasoningEvaluationJob) -> None:
        self._table.put_item(Item=_to_item(job))

    def get(self, alert_id: UUID) -> ReasoningEvaluationJob | None:
        item = self._table.get_item(
            Key={"alert_id": str(alert_id)}, ConsistentRead=True
        ).get("Item")
        return _from_item(item) if item else None

    def list_by_status(
        self, status: ReasoningEvaluationJobStatus, *, older_than: datetime, limit: int
    ) -> list[ReasoningEvaluationJob]:
        response = self._table.query(
            IndexName=STATUS_INDEX,
            KeyConditionExpression=Key("status").eq(status.value)
            & Key("queued_at").lt(_iso(older_than)),
            Limit=max(1, limit),
        )
        return [_from_item(item) for item in response.get("Items", [])]


def _iso(moment: datetime) -> str:
    # UTC everywhere so the string comparison in the index is chronological.
    return moment.astimezone(UTC).isoformat()


def _to_item(job: ReasoningEvaluationJob) -> dict[str, Any]:
    item: dict[str, Any] = {
        "alert_id": str(job.alert_id),
        "workflow_execution_id": str(job.workflow_execution_id),
        "status": job.status.value,
        "requested_by": job.requested_by,
        "queued_at": _iso(job.queued_at),
        "attempts": job.attempts,
        "run_ms": job.run_ms,
    }
    if job.started_at is not None:
        item["started_at"] = _iso(job.started_at)
    if job.finished_at is not None:
        item["finished_at"] = _iso(job.finished_at)
    if job.error_code:
        item["error_code"] = job.error_code
    return item


def _from_item(item: dict[str, Any]) -> ReasoningEvaluationJob:
    return ReasoningEvaluationJob(
        alert_id=UUID(item["alert_id"]),
        workflow_execution_id=UUID(item["workflow_execution_id"]),
        status=ReasoningEvaluationJobStatus(item["status"]),
        requested_by=str(item.get("requested_by") or "workflow"),
        queued_at=datetime.fromisoformat(item["queued_at"]),
        started_at=(
            datetime.fromisoformat(item["started_at"])
            if item.get("started_at")
            else None
        ),
        finished_at=(
            datetime.fromisoformat(item["finished_at"])
            if item.get("finished_at")
            else None
        ),
        attempts=int(item.get("attempts") or 0),
        error_code=item.get("error_code"),
        run_ms=int(item.get("run_ms") or 0),
    )
