from __future__ import annotations

from src.application.ports.flag_library_port import FlagLibraryRepository


class DeleteFlagLibraryEntryUseCase:
    def __init__(self, flag_library_repository: FlagLibraryRepository) -> None:
        self._entries = flag_library_repository

    def execute(self, entry_id: str) -> None:
        self._entries.delete(entry_id)
