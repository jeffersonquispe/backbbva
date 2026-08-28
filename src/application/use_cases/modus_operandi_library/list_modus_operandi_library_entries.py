from __future__ import annotations

from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryEntry,
    ModusOperandiLibraryRepository,
)


class ListModusOperandiLibraryEntriesUseCase:
    def __init__(
        self, modus_operandi_library_repository: ModusOperandiLibraryRepository
    ) -> None:
        self._entries = modus_operandi_library_repository

    def execute(self, *, active_only: bool = False) -> list[ModusOperandiLibraryEntry]:
        return self._entries.list(active_only=active_only)
