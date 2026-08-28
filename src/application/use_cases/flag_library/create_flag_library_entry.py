from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.configuration_port import FlagType
from src.application.ports.flag_library_port import FlagLibraryEntry, FlagLibraryRepository


class CreateFlagLibraryEntryUseCase:
    def __init__(self, flag_library_repository: FlagLibraryRepository) -> None:
        self._entries = flag_library_repository

    def execute(
        self,
        flag_type: FlagType,
        name: str,
        description: str = "",
        evolved_variables: list[str] | None = None,
        modus_operandi_library_ids: list[str] | None = None,
    ) -> FlagLibraryEntry:
        now = datetime.now(timezone.utc)
        return self._entries.create(
            FlagLibraryEntry(
                id=str(uuid.uuid4()),
                flag_type=flag_type,
                name=name,
                description=description,
                evolved_variables=evolved_variables or [],
                modus_operandi_library_ids=modus_operandi_library_ids or [],
                created_at=now,
                updated_at=now,
            )
        )
