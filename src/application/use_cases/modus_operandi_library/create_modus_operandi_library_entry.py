from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryEntry,
    ModusOperandiLibraryRepository,
)


class CreateModusOperandiLibraryEntryUseCase:
    def __init__(
        self, modus_operandi_library_repository: ModusOperandiLibraryRepository
    ) -> None:
        self._entries = modus_operandi_library_repository

    def execute(
        self,
        title: str,
        narrative: str,
        taxonomy_library_id: str,
        evolved_variables: list[str] | None = None,
    ) -> ModusOperandiLibraryEntry:
        normalized_title = " ".join(title.split()).casefold()
        for existing in self._entries.list():
            if " ".join(existing.title.split()).casefold() == normalized_title:
                return existing
        now = datetime.now(timezone.utc)
        return self._entries.create(
            ModusOperandiLibraryEntry(
                id=str(uuid.uuid4()),
                title=title,
                narrative=narrative,
                taxonomy_library_id=taxonomy_library_id,
                evolved_variables=evolved_variables or [],
                created_at=now,
                updated_at=now,
            )
        )
