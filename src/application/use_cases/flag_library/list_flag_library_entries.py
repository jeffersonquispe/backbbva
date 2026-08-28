from __future__ import annotations

from src.application.ports.flag_library_port import FlagLibraryEntry, FlagLibraryRepository


class ListFlagLibraryEntriesUseCase:
    def __init__(self, flag_library_repository: FlagLibraryRepository) -> None:
        self._entries = flag_library_repository

    def execute(self, *, active_only: bool = False) -> list[FlagLibraryEntry]:
        return self._entries.list(active_only=active_only)
