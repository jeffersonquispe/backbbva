from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class ModusOperandiLibraryEntry:
    # Global, config-independent reference data - see taxonomy_library_port.py
    # for the snapshot-copy rationale. taxonomy_library_id points at a
    # TaxonomyLibraryEntry, not at any segment's local taxonomy.
    id: str
    title: str
    narrative: str
    taxonomy_library_id: str
    created_at: datetime
    updated_at: datetime
    evolved_variables: list[str] = field(default_factory=list)
    active: bool = True
    # Cached embedding of this entry's text representation (title +
    # narrative) - see taxonomy_library_port.py's `embedding` field for the
    # recycle-on-promote rationale.
    embedding: list[float] | None = None


class ModusOperandiLibraryRepository(Protocol):
    def create(self, entry: ModusOperandiLibraryEntry) -> ModusOperandiLibraryEntry:
        ...

    def get(self, entry_id: str) -> ModusOperandiLibraryEntry | None:
        ...

    def list(self, *, active_only: bool = False) -> list[ModusOperandiLibraryEntry]:
        ...

    def update(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        narrative: str | None = None,
        taxonomy_library_id: str | None = None,
        evolved_variables: list[str] | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
    ) -> ModusOperandiLibraryEntry | None:
        ...

    def delete(self, entry_id: str) -> None:
        ...
