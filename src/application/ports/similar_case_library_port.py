from __future__ import annotations

from typing import Protocol

from src.domain.fraud_knowledge.library_entities import SimilarCaseLibraryEntry


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
        embedding: list[float] | None = None,
    ) -> SimilarCaseLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
