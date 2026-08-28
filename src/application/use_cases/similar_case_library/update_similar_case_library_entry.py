from __future__ import annotations

from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryEntry,
    SimilarCaseLibraryRepository,
)


class SimilarCaseLibraryEntryNotFoundError(Exception):
    pass


class UpdateSimilarCaseLibraryEntryUseCase:
    def __init__(self, similar_case_library_repository: SimilarCaseLibraryRepository) -> None:
        self._entries = similar_case_library_repository

    def execute(
        self,
        entry_id: str,
        *,
        text: str | None = None,
        modus_operandi_library_id: str | None = None,
        taxonomy_library_id: str | None = None,
        active: bool | None = None,
    ) -> SimilarCaseLibraryEntry:
        updated = self._entries.update(
            entry_id,
            text=text,
            modus_operandi_library_id=modus_operandi_library_id,
            taxonomy_library_id=taxonomy_library_id,
            active=active,
        )
        if updated is None:
            raise SimilarCaseLibraryEntryNotFoundError(
                f"Similar case library entry not found: {entry_id}"
            )
        return updated
