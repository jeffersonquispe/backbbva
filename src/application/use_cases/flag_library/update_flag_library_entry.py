from __future__ import annotations

from src.application.ports.configuration_port import FlagType
from src.application.ports.flag_library_port import FlagLibraryEntry, FlagLibraryRepository


class FlagLibraryEntryNotFoundError(Exception):
    pass


class UpdateFlagLibraryEntryUseCase:
    def __init__(self, flag_library_repository: FlagLibraryRepository) -> None:
        self._entries = flag_library_repository

    def execute(
        self,
        entry_id: str,
        *,
        flag_type: FlagType | None = None,
        name: str | None = None,
        description: str | None = None,
        evolved_variables: list[str] | None = None,
        modus_operandi_library_ids: list[str] | None = None,
        active: bool | None = None,
    ) -> FlagLibraryEntry:
        updated = self._entries.update(
            entry_id,
            flag_type=flag_type,
            name=name,
            description=description,
            evolved_variables=evolved_variables,
            modus_operandi_library_ids=modus_operandi_library_ids,
            active=active,
        )
        if updated is None:
            raise FlagLibraryEntryNotFoundError(f"Flag library entry not found: {entry_id}")
        return updated
