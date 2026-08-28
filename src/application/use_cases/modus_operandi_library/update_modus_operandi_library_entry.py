from __future__ import annotations

from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryEntry,
    ModusOperandiLibraryRepository,
)


class ModusOperandiLibraryEntryNotFoundError(Exception):
    pass


class UpdateModusOperandiLibraryEntryUseCase:
    def __init__(
        self, modus_operandi_library_repository: ModusOperandiLibraryRepository
    ) -> None:
        self._entries = modus_operandi_library_repository

    def execute(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        narrative: str | None = None,
        taxonomy_library_id: str | None = None,
        evolved_variables: list[str] | None = None,
        active: bool | None = None,
    ) -> ModusOperandiLibraryEntry:
        updated = self._entries.update(
            entry_id,
            title=title,
            narrative=narrative,
            taxonomy_library_id=taxonomy_library_id,
            evolved_variables=evolved_variables,
            active=active,
        )
        if updated is None:
            raise ModusOperandiLibraryEntryNotFoundError(
                f"Modus operandi library entry not found: {entry_id}"
            )
        return updated
