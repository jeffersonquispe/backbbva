from __future__ import annotations

from src.application.ports.taxonomy_library_port import (
    TaxonomyLibraryEntry,
    TaxonomyLibraryRepository,
)


class TaxonomyLibraryEntryNotFoundError(Exception):
    pass


class UpdateTaxonomyLibraryEntryUseCase:
    def __init__(self, taxonomy_library_repository: TaxonomyLibraryRepository) -> None:
        self._entries = taxonomy_library_repository

    def execute(
        self,
        entry_id: str,
        *,
        code: str | None = None,
        name: str | None = None,
        description: str | None = None,
        variables: list[str] | None = None,
        examples: list[str] | None = None,
        active: bool | None = None,
    ) -> TaxonomyLibraryEntry:
        updated = self._entries.update(
            entry_id,
            code=code,
            name=name,
            description=description,
            variables=variables,
            examples=examples,
            active=active,
        )
        if updated is None:
            raise TaxonomyLibraryEntryNotFoundError(f"Taxonomy library entry not found: {entry_id}")
        return updated
