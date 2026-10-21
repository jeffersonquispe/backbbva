from __future__ import annotations

from datetime import datetime

import pytest

from src.application.ports.embedding_port import EmbeddingResult, EmbeddingUnitOfWork
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryEntry,
    SimilarCaseLibraryRevisionConflict,
)
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
        embedding: list[float] | None = None,
        expected_updated_at: datetime | None = None,
    ) -> SimilarCaseLibraryEntry | None:
        current = self.items.get(entry_id)
        if current is None:
            return None
        if expected_updated_at is not None and expected_updated_at != current.updated_at:
            raise SimilarCaseLibraryRevisionConflict("similar case changed during update")
        updated = SimilarCaseLibraryEntry(
            id=current.id,
            text=text if text is not None else current.text,
            modus_operandi_library_id=(
                modus_operandi_library_id
                if modus_operandi_library_id is not None
                else current.modus_operandi_library_id
            ),
            taxonomy_library_id=(
                taxonomy_library_id
                if taxonomy_library_id is not None
                else current.taxonomy_library_id
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
        return EmbeddingResult(
            vectors=[[0.1, 0.2, 0.3] for _ in texts], model="fake", dimensions=3
        )


class ScriptedEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    def __init__(self) -> None:
        self.calls: list[ScriptedEmbeddingUnitOfWork] = []

    def create(
        self, *, model: str, monitoring: MonitoringPort, operation_name: str
    ) -> EmbeddingUnitOfWork:
        uow = ScriptedEmbeddingUnitOfWork()
        self.calls.append(uow)
        return uow


class NullSpan(MonitoringSpan):
    def write_input(self, data) -> None:
        pass

    def write_result(self, data) -> None:
        pass

    def write_inner_logs(self, entries) -> None:
        pass

    def write_operation_metas(self, metadata) -> None:
        pass

    def record_dependency(self, name, kind, metadata=None) -> None:
        pass

    def finish(self, error=None) -> None:
        pass


class NullMonitoringPort(MonitoringPort):
    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        return NullSpan()


def _create_use_case(
    repo, embedding_factory: ScriptedEmbeddingUnitOfWorkFactory | None = None
) -> CreateSimilarCaseLibraryEntryUseCase:
    return CreateSimilarCaseLibraryEntryUseCase(
        repo,
        embedding_unit_of_work_factory=embedding_factory
        or ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


def _update_use_case(
    repo, embedding_factory: ScriptedEmbeddingUnitOfWorkFactory | None = None
) -> UpdateSimilarCaseLibraryEntryUseCase:
    return UpdateSimilarCaseLibraryEntryUseCase(
        repo,
        embedding_unit_of_work_factory=embedding_factory
        or ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )


def test_create_similar_case_library_entry_defaults_to_active_and_computes_embedding() -> (
    None
):
    repo = InMemorySimilarCaseLibraryRepository()
    use_case = _create_use_case(repo)

    entry = use_case.execute("texto del caso", "mo-1", "tx-1")

    assert entry.text == "texto del caso"
    assert entry.modus_operandi_library_id == "mo-1"
    assert entry.taxonomy_library_id == "tx-1"
    assert entry.active is True
    assert entry.embedding == [0.1, 0.2, 0.3]


def test_list_similar_case_library_entries_filters_active_only() -> None:
    repo = InMemorySimilarCaseLibraryRepository()
    create = _create_use_case(repo)
    list_entries = ListSimilarCaseLibraryEntriesUseCase(repo)

    entry = create.execute("caso 1", "mo-1", "tx-1")
    create.execute("caso 2", "mo-1", "tx-1")
    repo.update(entry.id, active=False)

    assert len(list_entries.execute()) == 2
    assert len(list_entries.execute(active_only=True)) == 1


def test_update_similar_case_library_entry_changes_fields_and_reembeds_on_text_change() -> (
    None
):
    repo = InMemorySimilarCaseLibraryRepository()
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    create = _create_use_case(repo, embedding_factory)
    update = _update_use_case(repo, embedding_factory)

    entry = create.execute("old text", "mo-1", "tx-1")
    calls_before = len(embedding_factory.calls)
    updated = update.execute(
        entry.id, text="new text", modus_operandi_library_id="mo-2"
    )

    assert updated.text == "new text"
    assert updated.modus_operandi_library_id == "mo-2"
    assert len(embedding_factory.calls) == calls_before + 1

    calls_before = len(embedding_factory.calls)
    deactivated = update.execute(entry.id, active=False)
    assert deactivated.active is False
    assert len(embedding_factory.calls) == calls_before
    assert deactivated.embedding == updated.embedding


def test_update_unknown_similar_case_library_entry_raises() -> None:
    repo = InMemorySimilarCaseLibraryRepository()
    update = _update_use_case(repo)

    with pytest.raises(SimilarCaseLibraryEntryNotFoundError):
        update.execute("missing", text="x")


def test_delete_similar_case_library_entry_removes_it() -> None:
    repo = InMemorySimilarCaseLibraryRepository()
    create = _create_use_case(repo)
    delete = DeleteSimilarCaseLibraryEntryUseCase(repo)
    list_entries = ListSimilarCaseLibraryEntriesUseCase(repo)

    entry = create.execute("caso", "mo-1", "tx-1")
    delete.execute(entry.id)

    assert list_entries.execute() == []
