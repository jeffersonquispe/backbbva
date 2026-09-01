from __future__ import annotations

from src.application.ports.channel_library_port import (
    ChannelLibraryEntry,
    ChannelLibraryRepository,
)


class ListChannelLibraryEntriesUseCase:
    def __init__(self, channel_library_repository: ChannelLibraryRepository) -> None:
        self._entries = channel_library_repository

    def execute(self, *, active_only: bool = False) -> list[ChannelLibraryEntry]:
        return self._entries.list(active_only=active_only)
