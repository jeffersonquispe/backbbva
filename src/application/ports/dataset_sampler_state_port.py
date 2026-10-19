from __future__ import annotations

from typing import Protocol

from src.domain.datasets.mature_sample_entities import DatasetSamplerState


class DatasetSamplerStateRepository(Protocol):
    def get(self, state_id: str) -> DatasetSamplerState | None: ...

    def update(self, state: DatasetSamplerState) -> DatasetSamplerState: ...
