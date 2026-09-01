from __future__ import annotations

from src.application.ports.channel_library_port import ChannelLibraryRepository


class DeleteChannelLibraryEntryUseCase:
    def __init__(self, channel_library_repository: ChannelLibraryRepository) -> None:
        self._entries = channel_library_repository

    def execute(self, entry_id: str) -> None:
        self._entries.delete(entry_id)
