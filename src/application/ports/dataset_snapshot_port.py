from __future__ import annotations

from typing import Protocol

from src.domain.datasets.mature_sample_entities import DatasetSnapshot


class DatasetSnapshotRepository(Protocol):
    def get(self, snapshot_id: str) -> DatasetSnapshot | None: ...

    def create(self, snapshot: DatasetSnapshot) -> DatasetSnapshot: ...

    def list_recent(self, limit: int) -> list[DatasetSnapshot]: ...

    def delete(self, snapshot_id: str) -> None: ...
