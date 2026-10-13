from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class TaxonomyLibraryEntry:
    # Global, config-independent reference data - a segment's
    # SegmentKnowledgeBaseSection "Importar de biblioteca" picker
    # snapshot-copies one of these into its own local taxonomies array
    # (see configuration_port.py's Taxonomy) rather than referencing it, so
    # editing this entry later never touches an already-built config.
    id: str
    code: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    variables: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    active: bool = True
    # Cached embedding of this entry's text representation (name +
    # description + examples), computed on create and refreshed on update
    # only when one of those fields actually changes - see
    # create_taxonomy_library_entry.py / update_taxonomy_library_entry.py.
    # Promotion (PromoteVectorStoreInstanceUseCase) reads this instead of
    # calling the embedding API again.
    embedding: list[float] | None = None


class TaxonomyLibraryRepository(Protocol):
    def create(self, entry: TaxonomyLibraryEntry) -> TaxonomyLibraryEntry: ...

    def get(self, entry_id: str) -> TaxonomyLibraryEntry | None: ...

    def list(self, *, active_only: bool = False) -> list[TaxonomyLibraryEntry]: ...

    def update(
        self,
        entry_id: str,
        *,
        code: str | None = None,
        name: str | None = None,
        description: str | None = None,
        variables: list[str] | None = None,
        examples: list[str] | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
    ) -> TaxonomyLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
