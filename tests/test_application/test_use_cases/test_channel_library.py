from __future__ import annotations

import pytest

from src.application.ports.channel_library_port import ChannelLibraryEntry
from src.application.use_cases.channel_library.create_channel_library_entry import (
    CreateChannelLibraryEntryUseCase,
)
from src.application.use_cases.channel_library.delete_channel_library_entry import (
    DeleteChannelLibraryEntryUseCase,
)
from src.application.use_cases.channel_library.list_channel_library_entries import (
    ListChannelLibraryEntriesUseCase,
)
from src.application.use_cases.channel_library.update_channel_library_entry import (
    ChannelLibraryEntryNotFoundError,
    UpdateChannelLibraryEntryUseCase,
)


class InMemoryChannelLibraryRepository:
    def __init__(self) -> None:
        self.items: dict[str, ChannelLibraryEntry] = {}

    def create(self, entry: ChannelLibraryEntry) -> ChannelLibraryEntry:
        self.items[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> ChannelLibraryEntry | None:
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False) -> list[ChannelLibraryEntry]:
        entries = list(self.items.values())
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        code: str | None = None,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> ChannelLibraryEntry | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        updated = ChannelLibraryEntry(
            id=current.id,
            code=code if code is not None else current.code,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


def test_create_channel_library_entry_defaults_to_active() -> None:
    repo = InMemoryChannelLibraryRepository()
    use_case = CreateChannelLibraryEntryUseCase(repo)

    entry = use_case.execute("tarjetas", "Tarjetas", "desc")

    assert entry.code == "tarjetas"
    assert entry.name == "Tarjetas"
    assert entry.active is True


def test_list_channel_library_entries_filters_active_only() -> None:
    repo = InMemoryChannelLibraryRepository()
    create = CreateChannelLibraryEntryUseCase(repo)
    list_entries = ListChannelLibraryEntriesUseCase(repo)

    entry = create.execute("tarjetas", "Tarjetas")
    create.execute("canales_digitales", "Canales digitales")
    repo.update(entry.id, active=False)

    assert len(list_entries.execute()) == 2
    assert len(list_entries.execute(active_only=True)) == 1


def test_update_channel_library_entry_changes_fields() -> None:
    repo = InMemoryChannelLibraryRepository()
    create = CreateChannelLibraryEntryUseCase(repo)
    update = UpdateChannelLibraryEntryUseCase(repo)

    entry = create.execute("old", "old name")
    updated = update.execute(entry.id, code="new", name="new name")

    assert updated.code == "new"
    assert updated.name == "new name"
    assert updated.active is True

    deactivated = update.execute(entry.id, active=False)
    assert deactivated.active is False


def test_update_unknown_channel_library_entry_raises() -> None:
    repo = InMemoryChannelLibraryRepository()
    update = UpdateChannelLibraryEntryUseCase(repo)

    with pytest.raises(ChannelLibraryEntryNotFoundError):
        update.execute("missing", name="x")


def test_delete_channel_library_entry_removes_it() -> None:
    repo = InMemoryChannelLibraryRepository()
    create = CreateChannelLibraryEntryUseCase(repo)
    delete = DeleteChannelLibraryEntryUseCase(repo)
    list_entries = ListChannelLibraryEntriesUseCase(repo)

    entry = create.execute("tarjetas", "Tarjetas")
    delete.execute(entry.id)

    assert list_entries.execute() == []
