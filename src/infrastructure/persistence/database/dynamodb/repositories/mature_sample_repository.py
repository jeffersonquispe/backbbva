from __future__ import annotations

from datetime import date, datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.dataset_sampler_state_port import (
    DatasetSamplerStateRepository,
)
from src.application.ports.dataset_snapshot_port import (
    DatasetSnapshotRepository,
)
from src.application.ports.mature_sampler_schema_mapping_port import (
    MatureSamplerSchemaMappingRepository,
)
from src.domain.datasets.mature_sample_entities import (
    DatasetSamplerState,
    DatasetSnapshot,
    MatureSamplerSchemaMapping,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

SNAPSHOTS_TABLE = "dataset_snapshots"
SAMPLER_STATE_TABLE = "dataset_sampler_state"
SNAPSHOT_GROUP = "mature-sampler"


class DynamoDatasetSnapshotRepository(DatasetSnapshotRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(SNAPSHOTS_TABLE)

    def get(self, snapshot_id: str) -> DatasetSnapshot | None:
        item = self._table.get_item(Key={"snapshot_id": snapshot_id}).get("Item")
        return _snapshot_from_item(item) if item else None

    def create(self, snapshot: DatasetSnapshot) -> DatasetSnapshot:
        try:
            self._table.put_item(
                Item=_snapshot_to_item(snapshot),
                ConditionExpression="attribute_not_exists(snapshot_id)",
            )
            return snapshot
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = self.get(snapshot.snapshot_id)
            if existing is None:
                raise
            return existing

    def list_recent(self, limit: int) -> list[DatasetSnapshot]:
        response = self._table.query(
            IndexName="CreatedAtIdx",
            KeyConditionExpression=Key("snapshot_group").eq(SNAPSHOT_GROUP),
            ScanIndexForward=False,
            Limit=max(1, min(limit, 120)),
        )
        return [_snapshot_from_item(item) for item in response.get("Items", [])]

    def delete(self, snapshot_id: str) -> None:
        self._table.delete_item(Key={"snapshot_id": snapshot_id})


class DynamoDatasetSamplerStateRepository(DatasetSamplerStateRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(SAMPLER_STATE_TABLE)

    def get(self, state_id: str) -> DatasetSamplerState | None:
        item = self._table.get_item(Key={"state_id": state_id}).get("Item")
        return _state_from_item(item) if item else None

    def update(self, state: DatasetSamplerState) -> DatasetSamplerState:
        self._table.put_item(Item=_state_to_item(state))
        return state


class DynamoMatureSamplerSchemaMappingRepository(MatureSamplerSchemaMappingRepository):
    """Stores the selected schema mapping in its own row of the sampler state table."""

    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(SAMPLER_STATE_TABLE)

    def get(self) -> MatureSamplerSchemaMapping:
        item = self._table.get_item(Key={"state_id": "schema_mapping"}).get("Item")
        if not item:
            return MatureSamplerSchemaMapping()
        value = from_dynamodb(item)
        return MatureSamplerSchemaMapping(
            target_field=str(value.get("target_field", "")),
            marking_date_field=str(value.get("marking_date_field", "")),
            label_value_mapping=dict(value.get("label_value_mapping") or {}),
        )

    def update(
        self, mapping: MatureSamplerSchemaMapping
    ) -> MatureSamplerSchemaMapping:
        self._table.put_item(
            Item=to_dynamodb(
                {
                    "state_id": "schema_mapping",
                    "target_field": mapping.target_field,
                    "marking_date_field": mapping.marking_date_field,
                    "label_value_mapping": mapping.label_value_mapping or {},
                }
            )
        )
        return mapping


def _snapshot_to_item(snapshot: DatasetSnapshot) -> dict[str, Any]:
    return to_dynamodb(
        {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_group": SNAPSHOT_GROUP,
            "specification": snapshot.specification,
            "period_start": snapshot.period_start.isoformat(),
            "period_end": snapshot.period_end.isoformat(),
            "maturing_days": snapshot.maturing_days,
            "strata_counts": snapshot.strata_counts,
            "partition_counts": snapshot.partition_counts,
            "schema_versions": list(snapshot.schema_versions),
            "content_hash": snapshot.content_hash,
            "trigger": snapshot.trigger,
            "dataset_refs": snapshot.dataset_refs,
            "created_at": snapshot.created_at.isoformat(),
        }
    )


def _snapshot_from_item(item: dict[str, Any]) -> DatasetSnapshot:
    value = from_dynamodb(item)
    return DatasetSnapshot(
        snapshot_id=str(value["snapshot_id"]),
        specification=value["specification"],
        period_start=date.fromisoformat(value["period_start"]),
        period_end=date.fromisoformat(value["period_end"]),
        maturing_days=int(value["maturing_days"]),
        strata_counts={key: int(count) for key, count in value["strata_counts"].items()},
        partition_counts={key: int(count) for key, count in value["partition_counts"].items()},
        schema_versions=tuple(int(version) for version in value["schema_versions"]),
        content_hash=str(value["content_hash"]),
        trigger=str(value["trigger"]),
        dataset_refs=dict(value["dataset_refs"]),
        created_at=datetime.fromisoformat(value["created_at"]),
    )


def _state_to_item(state: DatasetSamplerState) -> dict[str, Any]:
    return {
        "state_id": state.state_id,
        "last_snapshot_id": state.last_snapshot_id,
        "last_completed_at": (
            state.last_completed_at.isoformat() if state.last_completed_at else None
        ),
        "last_period_key": state.last_period_key,
        "matured_alert_count": state.matured_alert_count,
        "latest_strata_counts": state.latest_strata_counts or {},
    }


def _state_from_item(item: dict[str, Any]) -> DatasetSamplerState:
    return DatasetSamplerState(
        state_id=str(item["state_id"]),
        last_snapshot_id=item.get("last_snapshot_id"),
        last_completed_at=(
            datetime.fromisoformat(item["last_completed_at"])
            if item.get("last_completed_at")
            else None
        ),
        last_period_key=item.get("last_period_key"),
        matured_alert_count=int(item.get("matured_alert_count", 0)),
        latest_strata_counts={
            key: int(count)
            for key, count in from_dynamodb(item.get("latest_strata_counts") or {}).items()
        },
    )
