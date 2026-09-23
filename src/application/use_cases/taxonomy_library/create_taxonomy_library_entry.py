from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.taxonomy_library_port import (
    TaxonomyLibraryEntry,
    TaxonomyLibraryRepository,
)


class CreateTaxonomyLibraryEntryUseCase:
    def __init__(self, taxonomy_library_repository: TaxonomyLibraryRepository) -> None:
        self._entries = taxonomy_library_repository

    def execute(
        self,
        code: str,
        name: str,
        description: str = "",
        variables: list[str] | None = None,
        examples: list[str] | None = None,
    ) -> TaxonomyLibraryEntry:
        normalized_name = " ".join(name.split()).casefold()
        for existing in self._entries.list():
            if " ".join(existing.name.split()).casefold() == normalized_name:
                return existing
        now = datetime.now(timezone.utc)
        return self._entries.create(
            TaxonomyLibraryEntry(
                id=str(uuid.uuid4()),
                code=code,
                name=name,
                description=description,
                variables=variables or [],
                examples=examples or [],
                created_at=now,
                updated_at=now,
            )
        )
