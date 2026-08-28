from __future__ import annotations

import pytest

from src.application.ports.similar_case_library_port import SimilarCaseLibraryEntry
from src.application.use_cases.similar_case_library.create_similar_case_library_entry import (
    CreateSimilarCaseLibraryEntryUseCase,
)
from src.application.use_cases.similar_case_library.delete_similar_case_library_entry import (
    DeleteSimilarCaseLibraryEntryUseCase,
)
from src.application.use_cases.similar_case_library.list_similar_case_library_entries import (
    ListSimilarCaseLibraryEntriesUseCase,
)
from src.application.use_cases.similar_case_library.update_similar_case_library_entry import (
    SimilarCaseLibraryEntryNotFoundError,
    UpdateSimilarCaseLibraryEntryUseCase,
)


class InMemorySimilarCaseLibraryRepository:
    def __init__(self) -> None:
        self.items: dict[str, SimilarCaseLibraryEntry] = {}

    def create(self, entry: SimilarCaseLibraryEntry) -> SimilarCaseLibraryEntry:
        self.items[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> SimilarCaseLibraryEntry | None:
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False) -> list[SimilarCaseLibraryEntry]:
        entries = list(self.items.values())
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        text: str | None = None,
        modus_operandi_library_id: str | None = None,
        taxonomy_library_id: str | None = None,
        active: bool | None = None,
    ) -> SimilarCaseLibraryEntry | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        updated = SimilarCaseLibraryEntry(
            id=current.id,
            text=text if text is not None else current.text,
            modus_operandi_library_id=(
                modus_operandi_library_id
                if modus_operandi_library_id is not None
                else current.modus_operandi_library_id
            ),
            taxonomy_library_id=(
                taxonomy_library_id if taxonomy_library_id is not None else current.taxonomy_library_id
            ),
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


def test_create_similar_case_library_entry_defaults_to_active() -> None:
    repo = InMemorySimilarCaseLibraryRepository()
    use_case = CreateSimilarCaseLibraryEntryUseCase(repo)

    entry = use_case.execute("texto del caso", "mo-1", "tx-1")

    assert entry.text == "texto del caso"
    assert entry.modus_operandi_library_id == "mo-1"
    assert entry.taxonomy_library_id == "tx-1"
    assert entry.active is True


def test_list_similar_case_library_entries_filters_active_only() -> None:
    repo = InMemorySimilarCaseLibraryRepository()
    create = CreateSimilarCaseLibraryEntryUseCase(repo)
    list_entries = ListSimilarCaseLibraryEntriesUseCase(repo)

    entry = create.execute("caso 1", "mo-1", "tx-1")
    create.execute("caso 2", "mo-1", "tx-1")
    repo.update(entry.id, active=False)

    assert len(list_entries.execute()) == 2
    assert len(list_entries.execute(active_only=True)) == 1


def test_update_similar_case_library_entry_changes_fields() -> None:
    repo = InMemorySimilarCaseLibraryRepository()
    create = CreateSimilarCaseLibraryEntryUseCase(repo)
    update = UpdateSimilarCaseLibraryEntryUseCase(repo)

    entry = create.execute("old text", "mo-1", "tx-1")
    updated = update.execute(entry.id, text="new text", modus_operandi_library_id="mo-2")

    assert updated.text == "new text"
    assert updated.modus_operandi_library_id == "mo-2"

    deactivated = update.execute(entry.id, active=False)
    assert deactivated.active is False


def test_update_unknown_similar_case_library_entry_raises() -> None:
    repo = InMemorySimilarCaseLibraryRepository()
    update = UpdateSimilarCaseLibraryEntryUseCase(repo)

    with pytest.raises(SimilarCaseLibraryEntryNotFoundError):
        update.execute("missing", text="x")


def test_delete_similar_case_library_entry_removes_it() -> None:
    repo = InMemorySimilarCaseLibraryRepository()
    create = CreateSimilarCaseLibraryEntryUseCase(repo)
    delete = DeleteSimilarCaseLibraryEntryUseCase(repo)
    list_entries = ListSimilarCaseLibraryEntriesUseCase(repo)

    entry = create.execute("caso", "mo-1", "tx-1")
    delete.execute(entry.id)

    assert list_entries.execute() == []
