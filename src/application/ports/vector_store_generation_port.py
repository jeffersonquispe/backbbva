from __future__ import annotations

import builtins
from typing import Protocol

from src.domain.fraud_knowledge.vector_store_generations import (
    VectorStoreGeneration,
    VectorStoreGenerationStatus,
    VectorStoreManifestItem,
)

__all__ = [
    "VectorStoreGeneration",
    "VectorStoreGenerationRepository",
    "VectorStoreGenerationStatus",
    "VectorStoreManifestItem",
]


class VectorStoreGenerationRepository(Protocol):
    def create(self, generation: VectorStoreGeneration) -> VectorStoreGeneration:
        """Persists a new generation number; raises ConflictError when that
        number already exists (two concurrent builds of one instance)."""
        ...

    def get(self, instance_id: str, generation: int) -> VectorStoreGeneration | None: ...

    def update(self, generation: VectorStoreGeneration) -> VectorStoreGeneration: ...

    def list(
        self, instance_id: str | None = None
    ) -> builtins.list[VectorStoreGeneration]:
        """Generations of one instance (or all), oldest first."""
        ...
