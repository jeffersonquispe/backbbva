from __future__ import annotations

from src.application.ports.taxonomy_library_port import TaxonomyLibraryRepository


class DeleteTaxonomyLibraryEntryUseCase:
    def __init__(self, taxonomy_library_repository: TaxonomyLibraryRepository) -> None:
        self._entries = taxonomy_library_repository

    def execute(self, entry_id: str) -> None:
        self._entries.delete(entry_id)
