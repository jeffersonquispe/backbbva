from __future__ import annotations

from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)


class DeleteModusOperandiLibraryEntryUseCase:
    def __init__(
        self, modus_operandi_library_repository: ModusOperandiLibraryRepository
    ) -> None:
        self._entries = modus_operandi_library_repository

    def execute(self, entry_id: str) -> None:
        self._entries.delete(entry_id)
