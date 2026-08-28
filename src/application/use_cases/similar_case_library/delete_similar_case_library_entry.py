from __future__ import annotations

from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryRepository,
)


class DeleteSimilarCaseLibraryEntryUseCase:
    def __init__(self, similar_case_library_repository: SimilarCaseLibraryRepository) -> None:
        self._entries = similar_case_library_repository

    def execute(self, entry_id: str) -> None:
        self._entries.delete(entry_id)
