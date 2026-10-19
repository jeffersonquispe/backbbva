from __future__ import annotations

from src.application.ports.taxonomy_library_port import (
    TaxonomyLibraryRepository,
)
from src.domain.fraud_knowledge.library_entities import TaxonomyLibraryEntry


class ListTaxonomyLibraryEntriesUseCase:
    def __init__(self, taxonomy_library_repository: TaxonomyLibraryRepository) -> None:
        self._entries = taxonomy_library_repository

    def execute(self, *, active_only: bool = False) -> list[TaxonomyLibraryEntry]:
        return self._entries.list(active_only=active_only)
