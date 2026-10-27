from __future__ import annotations

from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.errors import ConflictError
from src.application.ports.vector_store_generation_port import (
    VectorStoreGeneration,
    VectorStoreGenerationRepository,
    VectorStoreGenerationStatus,
    VectorStoreManifestItem,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

VECTOR_STORE_GENERATIONS_TABLE_NAME = "vector_store_generations"


class DynamoVectorStoreGenerationRepository(VectorStoreGenerationRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(VECTOR_STORE_GENERATIONS_TABLE_NAME)

    def create(self, generation: VectorStoreGeneration) -> VectorStoreGeneration:
        try:
            self._table.put_item(
                Item=_to_item(generation),
                ConditionExpression="attribute_not_exists(generation)",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConflictError(
                    f"Generation {generation.generation} of vector store "
                    f"{generation.instance_id} already exists"
                ) from error
            raise
        return generation

    def get(self, instance_id: str, generation: int) -> VectorStoreGeneration | None:
        item = self._table.get_item(
            Key={"instance_id": instance_id, "generation": generation}, ConsistentRead=True
        ).get("Item")
        return _from_item(item) if item else None

    def update(self, generation: VectorStoreGeneration) -> VectorStoreGeneration:
        self._table.put_item(Item=_to_item(generation))
        return generation

    def list(self, instance_id: str | None = None) -> list[VectorStoreGeneration]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"ConsistentRead": True}
        while True:
            if instance_id is not None:
                response = self._table.query(
                    KeyConditionExpression=Key("instance_id").eq(instance_id),
                    **kwargs,
                )
            else:
                # Small table (instances x retained generations); the
                # retention job keeps it bounded.
                response = self._table.scan(**kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return sorted(
            (_from_item(item) for item in items),
            key=lambda item: (item.instance_id, item.generation),
        )


def _to_item(generation: VectorStoreGeneration) -> dict[str, Any]:
    return {
        "instance_id": generation.instance_id,
        "generation": generation.generation,
        "status": generation.status.value,
        "built_by": generation.built_by,
        "created_at": generation.created_at.isoformat(),
        "fingerprint": generation.fingerprint,
        "manifest": [
            {
                "asset_type": item.asset_type,
                "asset_id": item.asset_id,
                "asset_version": item.asset_version,
            }
            for item in generation.manifest
        ],
        "document_count": generation.document_count,
        "ready_at": generation.ready_at.isoformat() if generation.ready_at else None,
        "retired_at": generation.retired_at.isoformat()
        if generation.retired_at
        else None,
        "error": generation.error,
        "migrated": generation.migrated,
    }


def _from_item(item: dict[str, Any]) -> VectorStoreGeneration:
    return VectorStoreGeneration(
        instance_id=item["instance_id"],
        generation=int(item["generation"]),
        status=VectorStoreGenerationStatus(item["status"]),
        built_by=item.get("built_by", "Sistema"),
        created_at=datetime.fromisoformat(item["created_at"]),
        fingerprint=item.get("fingerprint", ""),
        manifest=tuple(
            VectorStoreManifestItem(
                asset_type=entry["asset_type"],
                asset_id=entry["asset_id"],
                asset_version=int(entry["asset_version"]),
            )
            for entry in item.get("manifest") or []
        ),
        document_count=int(item.get("document_count") or 0),
        ready_at=datetime.fromisoformat(item["ready_at"])
        if item.get("ready_at")
        else None,
        retired_at=datetime.fromisoformat(item["retired_at"])
        if item.get("retired_at")
        else None,
        error=item.get("error"),
        migrated=bool(item.get("migrated", False)),
    )
