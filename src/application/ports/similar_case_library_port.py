from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class SimilarCaseLibraryEntry:
    # Global, config-independent reference data - see taxonomy_library_port.py
    # for the snapshot-copy rationale. Mirrors the frontend's SimilarCase
    # shape (data/configs.ts): belongs to exactly one MO (+ its taxonomy,
    # denormalized), no many-to-many like flags.
    id: str
    text: str
    modus_operandi_library_id: str
    taxonomy_library_id: str
    created_at: datetime
    updated_at: datetime
    active: bool = True


class SimilarCaseLibraryRepository(Protocol):
    def create(self, entry: SimilarCaseLibraryEntry) -> SimilarCaseLibraryEntry:
        ...

    def get(self, entry_id: str) -> SimilarCaseLibraryEntry | None:
        ...

    def list(self, *, active_only: bool = False) -> list[SimilarCaseLibraryEntry]:
        ...

    def update(
        self,
        entry_id: str,
        *,
        text: str | None = None,
        modus_operandi_library_id: str | None = None,
        taxonomy_library_id: str | None = None,
        active: bool | None = None,
    ) -> SimilarCaseLibraryEntry | None:
        ...

    def delete(self, entry_id: str) -> None:
        ...
