from __future__ import annotations

import builtins
from datetime import datetime
from typing import Protocol

from src.domain.fraud_knowledge.library_entities import SimilarCaseLibraryEntry


class SimilarCaseLibraryRevisionConflict(Exception):
    """Raised if a similar case changed after an assistant draft was verified."""


class SimilarCaseLibraryRepository(Protocol):
    def create(self, entry: SimilarCaseLibraryEntry) -> SimilarCaseLibraryEntry: ...

    def get(self, entry_id: str) -> SimilarCaseLibraryEntry | None: ...

    def list(self, *, active_only: bool = False) -> list[SimilarCaseLibraryEntry]: ...

    def update(
        self,
        entry_id: str,
        *,
        text: str | None = None,
        modus_operandi_library_id: str | None = None,
        taxonomy_library_id: str | None = None,
        active: bool | None = None,
        embedding: builtins.list[float] | None = None,
        expected_updated_at: datetime | None = None,
    ) -> SimilarCaseLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
