from __future__ import annotations

import pytest

from src.application.ports.taxonomy_library_port import TaxonomyLibraryEntry
from src.application.use_cases.taxonomy_library.create_taxonomy_library_entry import (
    CreateTaxonomyLibraryEntryUseCase,
)
from src.application.use_cases.taxonomy_library.delete_taxonomy_library_entry import (
    DeleteTaxonomyLibraryEntryUseCase,
)
from src.application.use_cases.taxonomy_library.list_taxonomy_library_entries import (
    ListTaxonomyLibraryEntriesUseCase,
)
from src.application.use_cases.taxonomy_library.update_taxonomy_library_entry import (
    TaxonomyLibraryEntryNotFoundError,
    UpdateTaxonomyLibraryEntryUseCase,
)


class InMemoryTaxonomyLibraryRepository:
    def __init__(self) -> None:
        self.items: dict[str, TaxonomyLibraryEntry] = {}

    def create(self, entry: TaxonomyLibraryEntry) -> TaxonomyLibraryEntry:
        self.items[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> TaxonomyLibraryEntry | None:
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False) -> list[TaxonomyLibraryEntry]:
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
        variables: list[str] | None = None,
        examples: list[str] | None = None,
        active: bool | None = None,
    ) -> TaxonomyLibraryEntry | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        updated = TaxonomyLibraryEntry(
            id=current.id,
            code=code if code is not None else current.code,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            variables=variables if variables is not None else current.variables,
            examples=examples if examples is not None else current.examples,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


def test_create_taxonomy_library_entry_defaults_to_active() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    use_case = CreateTaxonomyLibraryEntryUseCase(repo)

    entry = use_case.execute("FRD-CARD", "Fraude con tarjeta", "desc", ["Saldo"], ["ej"])

    assert entry.code == "FRD-CARD"
    assert entry.variables == ["Saldo"]
    assert entry.examples == ["ej"]
    assert entry.active is True


def test_list_taxonomy_library_entries_filters_active_only() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    create = CreateTaxonomyLibraryEntryUseCase(repo)
    list_entries = ListTaxonomyLibraryEntriesUseCase(repo)

    entry = create.execute("FRD-CARD", "Fraude con tarjeta")
    create.execute("FRD-ACCT", "Fraude de cuenta")
    repo.update(entry.id, active=False)

    assert len(list_entries.execute()) == 2
    assert len(list_entries.execute(active_only=True)) == 1


def test_update_taxonomy_library_entry_changes_fields() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    create = CreateTaxonomyLibraryEntryUseCase(repo)
    update = UpdateTaxonomyLibraryEntryUseCase(repo)

    entry = create.execute("OLD", "old name")
    updated = update.execute(entry.id, code="NEW", name="new name")

    assert updated.code == "NEW"
    assert updated.name == "new name"
    assert updated.active is True

    deactivated = update.execute(entry.id, active=False)
    assert deactivated.active is False


def test_update_unknown_taxonomy_library_entry_raises() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    update = UpdateTaxonomyLibraryEntryUseCase(repo)

    with pytest.raises(TaxonomyLibraryEntryNotFoundError):
        update.execute("missing", name="x")


def test_delete_taxonomy_library_entry_removes_it() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    create = CreateTaxonomyLibraryEntryUseCase(repo)
    delete = DeleteTaxonomyLibraryEntryUseCase(repo)
    list_entries = ListTaxonomyLibraryEntriesUseCase(repo)

    entry = create.execute("FRD-CARD", "Fraude con tarjeta")
    delete.execute(entry.id)

    assert list_entries.execute() == []
