from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.datasets.mature_sample_entities import MatureSamplerSchemaMapping


class MatureSamplerSchemaMappingRepository(ABC):
    """Persist the manager-selected source fields for mature sampling."""

    @abstractmethod
    def get(self) -> MatureSamplerSchemaMapping:
        raise NotImplementedError

    @abstractmethod
    def update(self, mapping: MatureSamplerSchemaMapping) -> MatureSamplerSchemaMapping:
        raise NotImplementedError
