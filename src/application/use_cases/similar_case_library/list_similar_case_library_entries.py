from __future__ import annotations

from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryEntry,
    SimilarCaseLibraryRepository,
)


class ListSimilarCaseLibraryEntriesUseCase:
    def __init__(
        self, similar_case_library_repository: SimilarCaseLibraryRepository
    ) -> None:
        self._entries = similar_case_library_repository

    def execute(self, *, active_only: bool = False) -> list[SimilarCaseLibraryEntry]:
        return self._entries.list(active_only=active_only)
