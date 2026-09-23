from __future__ import annotations

import pytest

from src.application.ports.embedding_port import (
    EmbeddingResult,
    EmbeddingUnitOfWork,
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.modus_operandi_library_port import ModusOperandiLibraryEntry
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.use_cases.modus_operandi_library.create_modus_operandi_library_entry import (
    CreateModusOperandiLibraryEntryUseCase,
)
from src.application.use_cases.modus_operandi_library.delete_modus_operandi_library_entry import (
    DeleteModusOperandiLibraryEntryUseCase,
)
from src.application.use_cases.modus_operandi_library.list_modus_operandi_library_entries import (
    ListModusOperandiLibraryEntriesUseCase,
)
from src.application.use_cases.modus_operandi_library.update_modus_operandi_library_entry import (
    ModusOperandiLibraryEntryNotFoundError,
    UpdateModusOperandiLibraryEntryUseCase,
)


class InMemoryModusOperandiLibraryRepository:
    def __init__(self) -> None:
        self.items: dict[str, ModusOperandiLibraryEntry] = {}

    def create(self, entry: ModusOperandiLibraryEntry) -> ModusOperandiLibraryEntry:
        self.items[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> ModusOperandiLibraryEntry | None:
        return self.items.get(entry_id)

    def list(self, *, active_only: bool = False) -> list[ModusOperandiLibraryEntry]:
        entries = list(self.items.values())
        if active_only:
            entries = [e for e in entries if e.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        narrative: str | None = None,
        taxonomy_library_id: str | None = None,
        evolved_variables: list[str] | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
    ) -> ModusOperandiLibraryEntry | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        updated = ModusOperandiLibraryEntry(
            id=current.id,
            title=title if title is not None else current.title,
            narrative=narrative if narrative is not None else current.narrative,
            taxonomy_library_id=(
                taxonomy_library_id if taxonomy_library_id is not None else current.taxonomy_library_id
            ),
            evolved_variables=(
                evolved_variables if evolved_variables is not None else current.evolved_variables
            ),
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=current.updated_at,
            embedding=embedding if embedding is not None else current.embedding,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


class ScriptedEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[0.1, 0.2, 0.3] for _ in texts], model="fake", dimensions=3)


class ScriptedEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    def __init__(self) -> None:
        self.calls: list[ScriptedEmbeddingUnitOfWork] = []

    def create(self, *, model: str, monitoring: MonitoringPort, operation_name: str) -> EmbeddingUnitOfWork:
        uow = ScriptedEmbeddingUnitOfWork()
        self.calls.append(uow)
        return uow


class NullSpan(MonitoringSpan):
    def write_input(self, data) -> None: pass
    def write_result(self, data) -> None: pass
    def write_inner_logs(self, entries) -> None: pass
    def write_operation_metas(self, metadata) -> None: pass
    def record_dependency(self, name, kind, metadata=None) -> None: pass
    def finish(self, error=None) -> None: pass


class NullMonitoringPort(MonitoringPort):
    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        return NullSpan()


def _create_use_case(repo, embedding_factory: ScriptedEmbeddingUnitOfWorkFactory | None = None) -> CreateModusOperandiLibraryEntryUseCase:
    return CreateModusOperandiLibraryEntryUseCase(
        repo,
        embedding_unit_of_work_factory=embedding_factory or ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


def _update_use_case(repo, embedding_factory: ScriptedEmbeddingUnitOfWorkFactory | None = None) -> UpdateModusOperandiLibraryEntryUseCase:
    return UpdateModusOperandiLibraryEntryUseCase(
        repo,
        embedding_unit_of_work_factory=embedding_factory or ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


def test_create_modus_operandi_library_entry_defaults_to_active_and_computes_embedding() -> None:
    repo = InMemoryModusOperandiLibraryRepository()
    use_case = _create_use_case(repo)

    entry = use_case.execute("Vishing", "narrativa", "tx-1", ["Celular"])

    assert entry.title == "Vishing"
    assert entry.taxonomy_library_id == "tx-1"
    assert entry.evolved_variables == ["Celular"]
    assert entry.active is True
    assert entry.embedding == [0.1, 0.2, 0.3]


def test_list_modus_operandi_library_entries_filters_active_only() -> None:
    repo = InMemoryModusOperandiLibraryRepository()
    create = _create_use_case(repo)
    list_entries = ListModusOperandiLibraryEntriesUseCase(repo)

    entry = create.execute("Vishing", "narrativa", "tx-1")
    create.execute("Phishing", "narrativa", "tx-1")
    repo.update(entry.id, active=False)

    assert len(list_entries.execute()) == 2
    assert len(list_entries.execute(active_only=True)) == 1


def test_update_modus_operandi_library_entry_changes_fields_and_reembeds_on_text_change() -> None:
    repo = InMemoryModusOperandiLibraryRepository()
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    create = _create_use_case(repo, embedding_factory)
    update = _update_use_case(repo, embedding_factory)

    entry = create.execute("old-title", "narrativa", "tx-1")
    calls_before = len(embedding_factory.calls)
    updated = update.execute(entry.id, title="new-title", taxonomy_library_id="tx-2")

    assert updated.title == "new-title"
    assert updated.taxonomy_library_id == "tx-2"
    assert len(embedding_factory.calls) == calls_before + 1

    calls_before = len(embedding_factory.calls)
    deactivated = update.execute(entry.id, active=False)
    assert deactivated.active is False
    assert len(embedding_factory.calls) == calls_before
    assert deactivated.embedding == updated.embedding


def test_update_unknown_modus_operandi_library_entry_raises() -> None:
    repo = InMemoryModusOperandiLibraryRepository()
    update = _update_use_case(repo)

    with pytest.raises(ModusOperandiLibraryEntryNotFoundError):
        update.execute("missing", title="x")


def test_delete_modus_operandi_library_entry_removes_it() -> None:
    repo = InMemoryModusOperandiLibraryRepository()
    create = _create_use_case(repo)
    delete = DeleteModusOperandiLibraryEntryUseCase(repo)
    list_entries = ListModusOperandiLibraryEntriesUseCase(repo)

    entry = create.execute("Vishing", "narrativa", "tx-1")
    delete.execute(entry.id)

    assert list_entries.execute() == []
