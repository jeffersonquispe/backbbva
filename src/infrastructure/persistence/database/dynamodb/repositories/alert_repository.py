from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from src.application.ports.alert_port import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertResolutionMethod,
    AlertStatus,
    Mark,
)
from src.application.ports.object_storage_port import ObjectStorageRef
from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

TABLE_NAME = "alerts"
PARTITION = "alert"
# GSI on created_day (operations-timezone calendar day, "YYYY-MM-DD") +
# created_at - see schemas.ALERTS_TABLE.
CREATED_DAY_INDEX = "CreatedDayIdx"
# KEYS_ONLY GSI on status + created_at (R9) - see schemas.ALERTS_TABLE.
STATUS_INDEX = "StatusIdx"
# BatchGetItem's per-call key limit.
_BATCH_GET_LIMIT = 100
# Map attribute holding the AlertMetricsSnapshot. Written only by
# DynamoMetricsRollupRepository.apply (one transaction with the rollup
# deltas) - this repository only reads it, and update() never touches it.
METRICS_ATTRIBUTE = "metrics"


def created_day_for(created_at: datetime, timezone_name: str | None = None) -> str:
    """The GSI partition value: created_at's calendar day in the operations
    timezone (Bogota), not UTC."""
    tz = ZoneInfo(timezone_name or genai_config.OPERATIONS_TIMEZONE)
    return created_at.astimezone(tz).date().isoformat()


class DynamoAlertRepository:
    def __init__(self, timezone_name: str | None = None) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)
        self._timezone_name = timezone_name or genai_config.OPERATIONS_TIMEZONE

    def create(self, alert: AlertRecord) -> AlertRecord:
        self._table.put_item(Item=_to_item(alert, self._timezone_name))
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        response = self._table.get_item(
            Key={"partition": PARTITION, "alert_id": str(alert_id)}
        )
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)

    def update(
        self,
        alert_id: UUID,
        *,
        status: AlertStatus | None = None,
        async_operation_id: UUID | None = None,
        workflow_execution_id: UUID | None = None,
        configuration_id: str | None = None,
        configuration_version: int | None = None,
        schema_version: int | None = None,
        input: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
        history_prev_alerta: list[dict[str, Any]] | None = None,
        agent_output: dict[str, Any] | None = None,
        agent_output_ref: ObjectStorageRef | None = None,
    ) -> AlertRecord | None:
        # UpdateItem on just the given fields, never a whole-item put: the
        # metrics snapshot (and its snapshot_version guard) is written by a
        # separate transaction and must not be overwritten with a stale copy.
        names: dict[str, str] = {"#updated_at": "updated_at"}
        values: dict[str, Any] = {":updated_at": datetime.now(UTC).isoformat()}
        sets = ["#updated_at = :updated_at"]
        for field_name, value in (
            ("status", status.value if status else None),
            (
                "async_operation_id",
                str(async_operation_id) if async_operation_id else None,
            ),
            (
                "workflow_execution_id",
                str(workflow_execution_id) if workflow_execution_id else None,
            ),
            ("configuration_id", configuration_id),
            ("configuration_version", configuration_version),
            ("schema_version", schema_version),
            ("input", to_dynamodb(input) if input is not None else None),
            ("labels", to_dynamodb(labels) if labels is not None else None),
            (
                "history_prev_alerta",
                to_dynamodb(history_prev_alerta)
                if history_prev_alerta is not None
                else None,
            ),
            (
                "agent_output",
                to_dynamodb(agent_output) if agent_output is not None else None,
            ),
            (
                "agent_output_ref",
                to_dynamodb(
                    {
                        "bucket": agent_output_ref.bucket,
                        "key": agent_output_ref.key,
                        "uri": agent_output_ref.uri,
                    }
                )
                if agent_output_ref
                else None,
            ),
        ):
            if value is None:
                continue
            names[f"#{field_name}"] = field_name
            values[f":{field_name}"] = value
            sets.append(f"#{field_name} = :{field_name}")
        try:
            response = self._table.update_item(
                Key={"partition": PARTITION, "alert_id": str(alert_id)},
                UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression="attribute_exists(alert_id)",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        return _from_item(response["Attributes"])

    def delete(self, alert_id: UUID) -> None:
        self._table.delete_item(Key={"partition": PARTITION, "alert_id": str(alert_id)})

    def list_by_status(self, status: AlertStatus) -> list[AlertRecord]:
        # StatusIdx holds only keys: query it, then fetch the items. The
        # index may lag a status change, so re-check the fetched status.
        try:
            keys = self._status_index_keys(status)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ValidationException":
                raise
            return self._list_by_status_filtered(status)  # index not built yet
        items = [
            item for item in self._batch_get(keys) if item.get("status") == status.value
        ]
        return sorted((_from_item(item) for item in items), key=lambda a: a.created_at)

    def count_by_status(self, status: AlertStatus) -> int:
        count = 0
        kwargs: dict[str, Any] = {
            "IndexName": STATUS_INDEX,
            "KeyConditionExpression": Key("status").eq(status.value),
            "Select": "COUNT",
        }
        while True:
            response = self._table.query(**kwargs)
            count += response.get("Count", 0)
            if "LastEvaluatedKey" not in response:
                return count
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    def fill_missing_created_day(self, from_day: date, to_day: date) -> int:
        """One-off migration for the metrics backfill (R6): alerts written
        before the created_day attribute existed are absent from
        CreatedDayIdx. One pass over the alerts partition, reading only
        keys + created_at of the alerts lacking it, sets created_day on
        those whose operations-timezone day is in [from_day, to_day].
        Idempotent (if_not_exists). Returns how many it filled."""
        filled = 0
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("partition").eq(PARTITION),
            "FilterExpression": Attr("created_day").not_exists(),
            "ProjectionExpression": "alert_id, created_at",
        }
        while True:
            response = self._table.query(**kwargs)
            for item in response.get("Items", []):
                created_at = datetime.fromisoformat(item["created_at"])
                day = created_day_for(created_at, self._timezone_name)
                if not from_day.isoformat() <= day <= to_day.isoformat():
                    continue
                self._table.update_item(
                    Key={"partition": PARTITION, "alert_id": item["alert_id"]},
                    UpdateExpression="SET created_day = if_not_exists(created_day, :day)",
                    ConditionExpression="attribute_exists(alert_id)",
                    ExpressionAttributeValues={":day": day},
                )
                filled += 1
            if "LastEvaluatedKey" not in response:
                return filled
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    def _status_index_keys(self, status: AlertStatus) -> list[dict[str, Any]]:
        keys: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "IndexName": STATUS_INDEX,
            "KeyConditionExpression": Key("status").eq(status.value),
        }
        while True:
            response = self._table.query(**kwargs)
            keys.extend(
                {"partition": item["partition"], "alert_id": item["alert_id"]}
                for item in response.get("Items", [])
            )
            if "LastEvaluatedKey" not in response:
                return keys
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    def _batch_get(self, keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resource = get_dynamodb_resource()
        table_name = self._table.name
        items: list[dict[str, Any]] = []
        for start in range(0, len(keys), _BATCH_GET_LIMIT):
            request: dict[str, Any] = {
                table_name: {"Keys": keys[start : start + _BATCH_GET_LIMIT]}
            }
            while request:
                response = resource.batch_get_item(RequestItems=request)
                items.extend(response.get("Responses", {}).get(table_name, []))
                request = response.get("UnprocessedKeys") or {}
        return items

    def _list_by_status_filtered(self, status: AlertStatus) -> list[AlertRecord]:
        # Fallback while StatusIdx is missing: a Query on the single alerts
        # partition + filter, which still reads every alert.
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("partition").eq(PARTITION),
            "FilterExpression": Attr("status").eq(status.value),
        }
        while True:
            response = self._table.query(**kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return sorted((_from_item(item) for item in items), key=lambda a: a.created_at)

    def list_by_created_day(self, created_day: date) -> list[AlertRecord]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "IndexName": CREATED_DAY_INDEX,
            "KeyConditionExpression": Key("created_day").eq(created_day.isoformat()),
        }
        while True:
            response = self._table.query(**kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return sorted((_from_item(item) for item in items), key=lambda a: a.created_at)

    def page_by_created_day(
        self, created_day: date, *, before: datetime | None, limit: int
    ) -> list[AlertRecord]:
        # created_at is the index's sort key, stored as a UTC ISO string,
        # so a lexical "<" on it is a chronological "<".
        condition = Key("created_day").eq(created_day.isoformat())
        if before is not None:
            condition = condition & Key("created_at").lt(
                before.astimezone(UTC).isoformat()
            )
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "IndexName": CREATED_DAY_INDEX,
            "KeyConditionExpression": condition,
            "ScanIndexForward": False,
        }
        while len(items) < limit:
            kwargs["Limit"] = limit - len(items)
            response = self._table.query(**kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return [_from_item(item) for item in items[:limit]]


def snapshot_to_item(snapshot: AlertMetricsSnapshot) -> dict[str, Any]:
    """DynamoDB map for an AlertMetricsSnapshot (floats as Decimal,
    datetimes as ISO strings, None attributes dropped)."""
    raw: dict[str, Any] = {
        "origin": snapshot.origin,
        "segment": snapshot.segment,
        "channel": snapshot.channel,
        "subchannel": snapshot.subchannel,
        "amount": Decimal(str(snapshot.amount))
        if snapshot.amount is not None
        else None,
        "amount_tier": snapshot.amount_tier,
        "schema_version": snapshot.schema_version,
        "configuration_id": snapshot.configuration_id,
        "resolution_method": (
            snapshot.resolution_method.value if snapshot.resolution_method else None
        ),
        "mark": snapshot.mark.value,
        "fraud_label": snapshot.fraud_label.value,
        "marked_at": snapshot.marked_at.isoformat() if snapshot.marked_at else None,
        "fraud_reviewed_at": (
            snapshot.fraud_reviewed_at.isoformat()
            if snapshot.fraud_reviewed_at
            else None
        ),
        "fraud_review_count": snapshot.fraud_review_count,
        "resolution_time_seconds": (
            Decimal(str(snapshot.resolution_time_seconds))
            if snapshot.resolution_time_seconds is not None
            else None
        ),
        "status": snapshot.status.value if snapshot.status else None,
        "snapshot_version": snapshot.snapshot_version,
    }
    return {key: value for key, value in raw.items() if value is not None}


def snapshot_from_item(item: dict[str, Any] | None) -> AlertMetricsSnapshot | None:
    """Tolerant: missing/unknown attributes fall back to the dataclass
    defaults, so items written before a field existed still hydrate."""
    if not item:
        return None
    item = from_dynamodb(item)

    def _enum(enum_cls, value, default):
        try:
            return enum_cls(value) if value is not None else default
        except ValueError:
            return default

    def _dt(value):
        return datetime.fromisoformat(value) if value else None

    amount = item.get("amount")
    resolution_time = item.get("resolution_time_seconds")
    return AlertMetricsSnapshot(
        origin=item.get("origin"),
        segment=item.get("segment"),
        channel=item.get("channel"),
        subchannel=item.get("subchannel"),
        amount=float(amount) if amount is not None else None,
        amount_tier=item.get("amount_tier") or "unknown",
        schema_version=int(item["schema_version"])
        if item.get("schema_version") is not None
        else None,
        configuration_id=item.get("configuration_id"),
        resolution_method=_enum(
            AlertResolutionMethod, item.get("resolution_method"), None
        ),
        mark=_enum(Mark, item.get("mark"), Mark.PENDING),
        fraud_label=_enum(Mark, item.get("fraud_label"), Mark.PENDING),
        marked_at=_dt(item.get("marked_at")),
        fraud_reviewed_at=_dt(item.get("fraud_reviewed_at")),
        fraud_review_count=int(item.get("fraud_review_count") or 0),
        resolution_time_seconds=(
            float(resolution_time) if resolution_time is not None else None
        ),
        status=_enum(AlertStatus, item.get("status"), None),
        snapshot_version=int(item.get("snapshot_version") or 0),
    )


def _to_item(alert: AlertRecord, timezone_name: str | None = None) -> dict[str, Any]:
    item = {
        "partition": PARTITION,
        "alert_id": str(alert.id),
        "created_day": created_day_for(alert.created_at, timezone_name),
        "event_id": alert.event_id,
        "event_type": alert.event_type,
        "status": alert.status.value,
        "customer_id": alert.customer_id,
        "async_operation_id": (
            str(alert.async_operation_id) if alert.async_operation_id else None
        ),
        "workflow_execution_id": (
            str(alert.workflow_execution_id) if alert.workflow_execution_id else None
        ),
        "configuration_id": alert.configuration_id,
        "configuration_version": alert.configuration_version,
        "raw_payload_ref": (
            to_dynamodb(
                {
                    "bucket": alert.raw_payload_ref.bucket,
                    "key": alert.raw_payload_ref.key,
                    "uri": alert.raw_payload_ref.uri,
                }
            )
            if alert.raw_payload_ref
            else None
        ),
        "schema_version": alert.schema_version,
        "input": to_dynamodb(alert.input),
        "labels": to_dynamodb(alert.labels),
        "history_prev_alerta": to_dynamodb(alert.history_prev_alerta),
        "agent_output": to_dynamodb(alert.agent_output),
        "agent_output_ref": (
            to_dynamodb(
                {
                    "bucket": alert.agent_output_ref.bucket,
                    "key": alert.agent_output_ref.key,
                    "uri": alert.agent_output_ref.uri,
                }
            )
            if alert.agent_output_ref
            else None
        ),
        "created_at": alert.created_at.isoformat(),
        "updated_at": alert.updated_at.isoformat(),
    }
    if alert.metrics is not None:
        item[METRICS_ATTRIBUTE] = snapshot_to_item(alert.metrics)
    return item


def _from_item(item: dict[str, Any]) -> AlertRecord:
    return AlertRecord(
        id=UUID(item["alert_id"]),
        event_id=item["event_id"],
        event_type=item["event_type"],
        raw_payload_ref=(
            ObjectStorageRef(**from_dynamodb(item["raw_payload_ref"]))
            if item.get("raw_payload_ref")
            else None
        ),
        status=AlertStatus(item["status"]),
        customer_id=item.get("customer_id"),
        async_operation_id=(
            UUID(item["async_operation_id"]) if item.get("async_operation_id") else None
        ),
        workflow_execution_id=(
            UUID(item["workflow_execution_id"])
            if item.get("workflow_execution_id")
            else None
        ),
        configuration_id=item.get("configuration_id"),
        configuration_version=(
            int(item["configuration_version"])
            if item.get("configuration_version") is not None
            else None
        ),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        metrics=snapshot_from_item(item.get(METRICS_ATTRIBUTE)),
        schema_version=int(item["schema_version"])
        if item.get("schema_version") is not None
        else None,
        input=from_dynamodb(item.get("input") or {}),
        labels=from_dynamodb(item.get("labels") or {}),
        history_prev_alerta=from_dynamodb(item.get("history_prev_alerta") or []),
        agent_output=from_dynamodb(item.get("agent_output") or {}),
        agent_output_ref=(
            ObjectStorageRef(**from_dynamodb(item["agent_output_ref"]))
            if item.get("agent_output_ref")
            else None
        ),
    )
