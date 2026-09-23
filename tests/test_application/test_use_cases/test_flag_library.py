from __future__ import annotations

import pytest

from src.application.ports.configuration_port import FlagType
from src.application.ports.embedding_port import (
    EmbeddingResult,
    EmbeddingUnitOfWork,
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.flag_library_port import FlagLibraryEntry
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
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
        embedding: list[float] | None = None,
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


def _create_use_case(repo, embedding_factory: ScriptedEmbeddingUnitOfWorkFactory | None = None) -> CreateFlagLibraryEntryUseCase:
    return CreateFlagLibraryEntryUseCase(
        repo,
        embedding_unit_of_work_factory=embedding_factory or ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


def _update_use_case(repo, embedding_factory: ScriptedEmbeddingUnitOfWorkFactory | None = None) -> UpdateFlagLibraryEntryUseCase:
    return UpdateFlagLibraryEntryUseCase(
        repo,
        embedding_unit_of_work_factory=embedding_factory or ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


def test_create_flag_library_entry_defaults_to_active_and_computes_embedding() -> None:
    repo = InMemoryFlagLibraryRepository()
    use_case = _create_use_case(repo)

    entry = use_case.execute(FlagType.RED, "Transacción nocturna", "desc", ["Saldo"], ["mo-1"])

    assert entry.flag_type == FlagType.RED
    assert entry.modus_operandi_library_ids == ["mo-1"]
    assert entry.active is True
    assert entry.embedding == [0.1, 0.2, 0.3]


def test_list_flag_library_entries_filters_active_only() -> None:
    repo = InMemoryFlagLibraryRepository()
    create = _create_use_case(repo)
    list_entries = ListFlagLibraryEntriesUseCase(repo)

    entry = create.execute(FlagType.RED, "Flag roja")
    create.execute(FlagType.YELLOW, "Flag amarilla")
    repo.update(entry.id, active=False)

    assert len(list_entries.execute()) == 2
    assert len(list_entries.execute(active_only=True)) == 1


def test_update_flag_library_entry_changes_fields_and_reembeds_on_text_change() -> None:
    repo = InMemoryFlagLibraryRepository()
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    create = _create_use_case(repo, embedding_factory)
    update = _update_use_case(repo, embedding_factory)

    entry = create.execute(FlagType.RED, "old-name")
    calls_before = len(embedding_factory.calls)
    updated = update.execute(entry.id, name="new-name", flag_type=FlagType.YELLOW)

    assert updated.name == "new-name"
    assert updated.flag_type == FlagType.YELLOW
    assert len(embedding_factory.calls) == calls_before + 1

    calls_before = len(embedding_factory.calls)
    deactivated = update.execute(entry.id, active=False)
    assert deactivated.active is False
    assert len(embedding_factory.calls) == calls_before
    assert deactivated.embedding == updated.embedding


def test_update_unknown_flag_library_entry_raises() -> None:
    repo = InMemoryFlagLibraryRepository()
    update = _update_use_case(repo)

    with pytest.raises(FlagLibraryEntryNotFoundError):
        update.execute("missing", name="x")


def test_delete_flag_library_entry_removes_it() -> None:
    repo = InMemoryFlagLibraryRepository()
    create = _create_use_case(repo)
    delete = DeleteFlagLibraryEntryUseCase(repo)
    list_entries = ListFlagLibraryEntriesUseCase(repo)

    entry = create.execute(FlagType.RED, "Flag roja")
    delete.execute(entry.id)

    assert list_entries.execute() == []
