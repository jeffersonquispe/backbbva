from __future__ import annotations

import pytest

from src.application.ports.embedding_port import (
    EmbeddingResult,
    EmbeddingUnitOfWork,
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
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
        embedding: list[float] | None = None,
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
            embedding=embedding if embedding is not None else current.embedding,
        )
        self.items[entry_id] = updated
        return updated

    def delete(self, entry_id: str) -> None:
        self.items.pop(entry_id, None)


class ScriptedEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def __init__(self) -> None:
        self.embedded_texts: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.embedded_texts.append(list(texts))
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


def _create_use_case(repo, embedding_factory: ScriptedEmbeddingUnitOfWorkFactory | None = None) -> CreateTaxonomyLibraryEntryUseCase:
    return CreateTaxonomyLibraryEntryUseCase(
        repo,
        embedding_unit_of_work_factory=embedding_factory or ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


def _update_use_case(repo, embedding_factory: ScriptedEmbeddingUnitOfWorkFactory | None = None) -> UpdateTaxonomyLibraryEntryUseCase:
    return UpdateTaxonomyLibraryEntryUseCase(
        repo,
        embedding_unit_of_work_factory=embedding_factory or ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


def test_create_taxonomy_library_entry_defaults_to_active_and_computes_embedding() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    use_case = _create_use_case(repo)

    entry = use_case.execute("FRD-CARD", "Fraude con tarjeta", "desc", ["Saldo"], ["ej"])

    assert entry.code == "FRD-CARD"
    assert entry.variables == ["Saldo"]
    assert entry.examples == ["ej"]
    assert entry.active is True
    assert entry.embedding == [0.1, 0.2, 0.3]


def test_list_taxonomy_library_entries_filters_active_only() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    create = _create_use_case(repo)
    list_entries = ListTaxonomyLibraryEntriesUseCase(repo)

    entry = create.execute("FRD-CARD", "Fraude con tarjeta")
    create.execute("FRD-ACCT", "Fraude de cuenta")
    repo.update(entry.id, active=False)

    assert len(list_entries.execute()) == 2
    assert len(list_entries.execute(active_only=True)) == 1


def test_update_taxonomy_library_entry_changes_fields_and_reembeds_on_text_change() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    create = _create_use_case(repo, embedding_factory)
    update = _update_use_case(repo, embedding_factory)

    entry = create.execute("OLD", "old name")
    calls_before = len(embedding_factory.calls)
    updated = update.execute(entry.id, code="NEW", name="new name")

    assert updated.code == "NEW"
    assert updated.name == "new name"
    assert updated.active is True
    # name changed -> re-embedded.
    assert len(embedding_factory.calls) == calls_before + 1

    calls_before = len(embedding_factory.calls)
    deactivated = update.execute(entry.id, active=False)
    assert deactivated.active is False
    # active-only change -> no re-embedding, previous embedding recycled.
    assert len(embedding_factory.calls) == calls_before
    assert deactivated.embedding == updated.embedding


def test_update_unknown_taxonomy_library_entry_raises() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    update = _update_use_case(repo)

    with pytest.raises(TaxonomyLibraryEntryNotFoundError):
        update.execute("missing", name="x")


def test_delete_taxonomy_library_entry_removes_it() -> None:
    repo = InMemoryTaxonomyLibraryRepository()
    create = _create_use_case(repo)
    delete = DeleteTaxonomyLibraryEntryUseCase(repo)
    list_entries = ListTaxonomyLibraryEntriesUseCase(repo)

    entry = create.execute("FRD-CARD", "Fraude con tarjeta")
    delete.execute(entry.id)

    assert list_entries.execute() == []
