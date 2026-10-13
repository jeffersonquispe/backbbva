from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstance,
    VectorStoreInstanceAsset,
    VectorStoreInstanceRepository,
)


class VectorStoreInstanceNotFoundError(ValueError):
    pass


class UpdateVectorStoreInstanceUseCase:
    def __init__(self, repository: VectorStoreInstanceRepository) -> None:
        self._repository = repository

    def execute(self, instance_id: str, *, name: str | None, description: str | None, actor: str) -> VectorStoreInstance:
        current = self._repository.get(instance_id)
        if current is None:
            raise VectorStoreInstanceNotFoundError(f"Vector store instance not found: {instance_id}")
        return self._repository.update(replace(
            current,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            updated_at=datetime.now(UTC),
            updated_by=actor,
        ))


class AddVectorStoreDocumentUseCase:
    """Creates only the instance-to-document relation, never an embedding."""

    def __init__(self, repository: VectorStoreInstanceRepository) -> None:
        self._repository = repository

    def execute(self, instance_id: str, *, asset_type: KnowledgeAssetType, asset_id: str, actor: str, asset_version: int = 1) -> VectorStoreInstanceAsset:
        instance = self._repository.get(instance_id)
        if instance is None:
            raise VectorStoreInstanceNotFoundError(f"Vector store instance not found: {instance_id}")
        asset = self._repository.add_asset(VectorStoreInstanceAsset(
            vector_store_instance_id=instance_id,
            asset_type=asset_type,
            asset_id=asset_id,
            asset_version=asset_version,
        ))
        self._repository.update(replace(instance, updated_at=datetime.now(UTC), updated_by=actor))
        return asset


class RemoveVectorStoreDocumentUseCase:
    def __init__(self, repository: VectorStoreInstanceRepository) -> None:
        self._repository = repository

    def execute(self, instance_id: str, relation_id: str, *, actor: str) -> None:
        instance = self._repository.get(instance_id)
        if instance is None:
            raise VectorStoreInstanceNotFoundError(f"Vector store instance not found: {instance_id}")
        self._repository.remove_asset(instance_id, relation_id)
        self._repository.update(replace(instance, updated_at=datetime.now(UTC), updated_by=actor))
