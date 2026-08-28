from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryEntry,
    SimilarCaseLibraryRepository,
)


class CreateSimilarCaseLibraryEntryUseCase:
    def __init__(self, similar_case_library_repository: SimilarCaseLibraryRepository) -> None:
        self._entries = similar_case_library_repository

    def execute(
        self, text: str, modus_operandi_library_id: str, taxonomy_library_id: str
    ) -> SimilarCaseLibraryEntry:
        now = datetime.now(timezone.utc)
        return self._entries.create(
            SimilarCaseLibraryEntry(
                id=str(uuid.uuid4()),
                text=text,
                modus_operandi_library_id=modus_operandi_library_id,
                taxonomy_library_id=taxonomy_library_id,
                created_at=now,
                updated_at=now,
            )
        )
