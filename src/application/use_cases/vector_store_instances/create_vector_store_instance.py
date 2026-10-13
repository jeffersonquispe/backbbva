from __future__ import annotations

from datetime import UTC, datetime

from src.application.ports.vector_store_instance_port import (
    VectorStoreInstance,
    VectorStoreInstanceAsset,
    VectorStoreInstanceRepository,
)


class DuplicateVectorStoreInstanceNameError(ValueError):
    pass


class CreateVectorStoreInstanceUseCase:
    def __init__(self, repository: VectorStoreInstanceRepository) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        name: str,
        description: str,
        created_by: str,
        assets: list[VectorStoreInstanceAsset],
    ) -> VectorStoreInstance:
        """Create the next immutable instance from already-vectorized assets.

        Asset embeddings are copied by value into the relation table.  This is
        what makes a vector-store version reproducible even if the source
        asset later receives a new embedding.
        """
        instances = self._repository.list()
        normalized_name = name.strip().casefold()
        if any(item.name.strip().casefold() == normalized_name for item in instances):
            raise DuplicateVectorStoreInstanceNameError(
                f"A vector store instance named {name!r} already exists"
            )
        version = max((item.version for item in instances), default=0) + 1
        instance = VectorStoreInstance(
            id=f"vector-store-v{version}", version=version, name=name.strip(),
            description=description, created_at=datetime.now(UTC),
            created_by=created_by,
        )
        normalized = [
            VectorStoreInstanceAsset(
                vector_store_instance_id=instance.id,
                asset_type=asset.asset_type,
                asset_id=asset.asset_id,
                asset_version=asset.asset_version,
                embedding=list(asset.embedding),
            )
            for asset in assets
        ]
        return self._repository.create(instance, normalized)
