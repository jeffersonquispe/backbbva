from __future__ import annotations

import pytest

from src.application.ports.configuration_port import FlagType
from src.application.ports.flag_library_port import FlagLibraryEntry
from src.application.use_cases.flag_library.create_flag_library_entry import (
    CreateFlagLibraryEntryUseCase,
)
from src.application.use_cases.flag_library.delete_flag_library_entry import (
    DeleteFlagLibraryEntryUseCase,
)
from src.application.use_cases.flag_library.list_flag_library_entries import (
    ListFlagLibraryEntriesUseCase,
)
from src.application.use_cases.flag_library.update_flag_library_entry import (
    FlagLibraryEntryNotFoundError,
    UpdateFlagLibraryEntryUseCase,
)


class InMemoryFlagLibraryRepository:
    def __init__(self) -> None:
        self.items: dict[str, FlagLibraryEntry] = {}

    def create(self, entry: FlagLibraryEntry) -> FlagLibraryEntry:
        self.items[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> FlagLibraryEntry | None:
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False) -> list[FlagLibraryEntry]:
        entries = list(self.items.values())
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        flag_type: FlagType | None = None,
        name: str | None = None,
        description: str | None = None,
        evolved_variables: list[str] | None = None,
        modus_operandi_library_ids: list[str] | None = None,
        active: bool | None = None,
    ) -> FlagLibraryEntry | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        updated = FlagLibraryEntry(
            id=current.id,
            flag_type=flag_type if flag_type is not None else current.flag_type,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            evolved_variables=(
                evolved_variables if evolved_variables is not None else current.evolved_variables
            ),
            modus_operandi_library_ids=(
                modus_operandi_library_ids
                if modus_operandi_library_ids is not None
                else current.modus_operandi_library_ids
            ),
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


def test_create_flag_library_entry_defaults_to_active() -> None:
    repo = InMemoryFlagLibraryRepository()
    use_case = CreateFlagLibraryEntryUseCase(repo)

    entry = use_case.execute(FlagType.RED, "Transacción nocturna", "desc", ["Saldo"], ["mo-1"])

    assert entry.flag_type == FlagType.RED
    assert entry.modus_operandi_library_ids == ["mo-1"]
    assert entry.active is True


def test_list_flag_library_entries_filters_active_only() -> None:
    repo = InMemoryFlagLibraryRepository()
    create = CreateFlagLibraryEntryUseCase(repo)
    list_entries = ListFlagLibraryEntriesUseCase(repo)

    entry = create.execute(FlagType.RED, "Flag roja")
    create.execute(FlagType.YELLOW, "Flag amarilla")
    repo.update(entry.id, active=False)

    assert len(list_entries.execute()) == 2
    assert len(list_entries.execute(active_only=True)) == 1


def test_update_flag_library_entry_changes_fields() -> None:
    repo = InMemoryFlagLibraryRepository()
    create = CreateFlagLibraryEntryUseCase(repo)
    update = UpdateFlagLibraryEntryUseCase(repo)

    entry = create.execute(FlagType.RED, "old-name")
    updated = update.execute(entry.id, name="new-name", flag_type=FlagType.YELLOW)

    assert updated.name == "new-name"
    assert updated.flag_type == FlagType.YELLOW

    deactivated = update.execute(entry.id, active=False)
    assert deactivated.active is False


def test_update_unknown_flag_library_entry_raises() -> None:
    repo = InMemoryFlagLibraryRepository()
    update = UpdateFlagLibraryEntryUseCase(repo)

    with pytest.raises(FlagLibraryEntryNotFoundError):
        update.execute("missing", name="x")


def test_delete_flag_library_entry_removes_it() -> None:
    repo = InMemoryFlagLibraryRepository()
    create = CreateFlagLibraryEntryUseCase(repo)
    delete = DeleteFlagLibraryEntryUseCase(repo)
    list_entries = ListFlagLibraryEntriesUseCase(repo)

    entry = create.execute(FlagType.RED, "Flag roja")
    delete.execute(entry.id)

    assert list_entries.execute() == []
