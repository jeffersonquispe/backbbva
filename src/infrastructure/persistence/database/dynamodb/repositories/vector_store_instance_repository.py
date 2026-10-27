from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstance,
    VectorStoreInstanceAsset,
    VectorStoreInstanceRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

VECTOR_STORE_INSTANCES_TABLE_NAME = "vector_store_instances"
VECTOR_STORE_INSTANCE_ASSETS_TABLE_NAME = "vector_store_instance_assets"


class DynamoVectorStoreInstanceRepository(VectorStoreInstanceRepository):
    def __init__(self) -> None:
        resource = get_dynamodb_resource()
        self._instances = resource.Table(VECTOR_STORE_INSTANCES_TABLE_NAME)
        self._assets = resource.Table(VECTOR_STORE_INSTANCE_ASSETS_TABLE_NAME)

    def create(
        self, instance: VectorStoreInstance, assets: list[VectorStoreInstanceAsset]
    ) -> VectorStoreInstance:
        # A deterministic vN id plus this condition prevents a duplicate
        # version from being persisted when two admins create a snapshot.
        self._instances.put_item(
            Item=_instance_to_item(instance),
            ConditionExpression="attribute_not_exists(id)",
        )
        for asset in assets:
            self._assets.put_item(Item=_asset_to_item(asset))
        return instance

    def list(self) -> list[VectorStoreInstance]:
        return sorted(
            (
                _instance_from_item(item)
                for item in self._instances.scan().get("Items", [])
            ),
            key=lambda instance: instance.version,
        )

    def get(self, instance_id: str) -> VectorStoreInstance | None:
        item = self._instances.get_item(Key={"id": instance_id}).get("Item")
        return _instance_from_item(item) if item else None

    def update(self, instance: VectorStoreInstance) -> VectorStoreInstance:
        # SET only the mapped attributes: a pre-generations row keeps its
        # legacy promoted_version until vector_store_generation_migration.py
        # has turned it into a generation record.
        item = _instance_to_item(instance)
        item.pop("id")
        names = {f"#a{index}": key for index, key in enumerate(item)}
        values = {f":v{index}": value for index, value in enumerate(item.values())}
        self._instances.update_item(
            Key={"id": instance.id},
            UpdateExpression="SET "
            + ", ".join(f"#a{index} = :v{index}" for index in range(len(item))),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        return instance

    def list_assets(self, instance_id: str) -> list[VectorStoreInstanceAsset]:
        response = self._assets.query(
            KeyConditionExpression=Key("vector_store_instance_id").eq(instance_id)
        )
        return [_asset_from_item(item) for item in response.get("Items", [])]

    def add_asset(self, asset: VectorStoreInstanceAsset) -> VectorStoreInstanceAsset:
        self._assets.put_item(
            Item=_asset_to_item(asset),
            ConditionExpression="attribute_not_exists(vector_store_instance_id) AND attribute_not_exists(relation_id)",
        )
        return asset

    def remove_asset(self, instance_id: str, relation_id: str) -> None:
        # This removes only the relation row. The asset's library document is
        # intentionally never touched.
        self._assets.delete_item(
            Key={"vector_store_instance_id": instance_id, "relation_id": relation_id}
        )


def _instance_to_item(instance: VectorStoreInstance) -> dict[str, Any]:
    return {
        "id": instance.id,
        "version": instance.version,
        "name": instance.name,
        "description": instance.description,
        "created_at": instance.created_at.isoformat(),
        "created_by": instance.created_by,
        "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
        "updated_by": instance.updated_by,
    }


def _instance_from_item(item: dict[str, Any]) -> VectorStoreInstance:
    return VectorStoreInstance(
        id=item["id"],
        version=int(item["version"]),
        name=item.get("name", f"v{item['version']}"),
        description=item.get("description", ""),
        created_at=datetime.fromisoformat(item["created_at"]),
        created_by=item.get("created_by", "Sistema"),
        updated_at=datetime.fromisoformat(item["updated_at"])
        if item.get("updated_at")
        else None,
        updated_by=item.get("updated_by"),
    )


def _asset_from_item(item: dict[str, Any]) -> VectorStoreInstanceAsset:
    return VectorStoreInstanceAsset(
        vector_store_instance_id=item["vector_store_instance_id"],
        asset_type=KnowledgeAssetType(item["asset_type"]),
        asset_id=item["asset_id"],
        asset_version=int(item["asset_version"]),
        embedding=[float(v) for v in item["embedding"]]
        if item.get("embedding") is not None
        else None,
        origin=item.get("origin", "manual"),
        root_asset_type=KnowledgeAssetType(item["root_asset_type"])
        if item.get("root_asset_type")
        else None,
        root_asset_id=item.get("root_asset_id"),
        follow_source_updates=bool(item.get("follow_source_updates", True)),
    )


def _asset_to_item(asset: VectorStoreInstanceAsset) -> dict[str, Any]:
    return {
        "vector_store_instance_id": asset.vector_store_instance_id,
        "relation_id": asset.relation_id,
        "asset_type": asset.asset_type.value,
        "asset_id": asset.asset_id,
        "asset_version": asset.asset_version,
        "embedding": (
            [Decimal(str(value)) for value in asset.embedding]
            if asset.embedding is not None
            else None
        ),
        "origin": asset.origin,
        "root_asset_type": asset.root_asset_type.value
        if asset.root_asset_type
        else None,
        "root_asset_id": asset.root_asset_id,
        "follow_source_updates": asset.follow_source_updates,
    }
