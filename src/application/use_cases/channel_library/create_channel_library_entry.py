from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.ports.channel_library_port import (
    ChannelLibraryEntry,
    ChannelLibraryRepository,
)


class CreateChannelLibraryEntryUseCase:
    def __init__(self, channel_library_repository: ChannelLibraryRepository) -> None:
        self._entries = channel_library_repository

    def execute(
        self,
        code: str,
        name: str,
        description: str = "",
    ) -> ChannelLibraryEntry:
        now = datetime.now(UTC)
        return self._entries.create(
            ChannelLibraryEntry(
                id=str(uuid.uuid4()),
                code=code,
                name=name,
                description=description,
                created_at=now,
                updated_at=now,
            )
        )
