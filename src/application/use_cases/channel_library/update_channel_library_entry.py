from __future__ import annotations

from src.application.ports.channel_library_port import (
    ChannelLibraryEntry,
    ChannelLibraryRepository,
)


class ChannelLibraryEntryNotFoundError(Exception):
    pass


class UpdateChannelLibraryEntryUseCase:
    def __init__(self, channel_library_repository: ChannelLibraryRepository) -> None:
        self._entries = channel_library_repository

    def execute(
        self,
        entry_id: str,
        *,
        code: str | None = None,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> ChannelLibraryEntry:
        updated = self._entries.update(
            entry_id,
            code=code,
            name=name,
            description=description,
            active=active,
        )
        if updated is None:
            raise ChannelLibraryEntryNotFoundError(f"Channel library entry not found: {entry_id}")
        return updated
