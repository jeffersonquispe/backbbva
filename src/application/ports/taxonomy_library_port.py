from __future__ import annotations

import builtins
from typing import Protocol

from src.domain.fraud_knowledge.library_entities import TaxonomyLibraryEntry


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
        variables: builtins.list[str] | None = None,
        examples: builtins.list[str] | None = None,
        active: bool | None = None,
        embedding: builtins.list[float] | None = None,
    ) -> TaxonomyLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
