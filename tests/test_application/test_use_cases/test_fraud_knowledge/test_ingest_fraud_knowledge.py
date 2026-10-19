from __future__ import annotations

import uuid

import pytest

from src.application.ports.embedding_port import EmbeddingResult, EmbeddingUnitOfWork
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
    ModusOperandiDocument,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.application.use_cases.fraud_knowledge.ingest_flag import (
    IngestFlagInput,
    IngestFlagUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_modus_operandi import (
    IngestModusOperandiInput,
    IngestModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_similar_case import (
    IngestSimilarCaseInput,
    IngestSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_taxonomia import (
    IngestTaxonomiaInput,
    IngestTaxonomiaUseCase,
)


class InMemoryFraudKnowledgeRepository:
    def __init__(self) -> None:
        self._documents: dict[uuid.UUID, FraudKnowledgeDocument] = {}

    def create(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._documents[document.id] = document
        return document

    def get(self, document_id: uuid.UUID) -> FraudKnowledgeDocument | None:
        return self._documents.get(document_id)

    def update(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._documents[document.id] = document
        return document

    def delete(self, document_id: uuid.UUID) -> None:
        self._documents.pop(document_id, None)

    def list(
        self,
        document_type: DocumentType | None = None,
        *,
        vector_store_id: str | None = None,
        vector_store_version: int | None = None,
    ) -> list[FraudKnowledgeDocument]:
        results = list(self._documents.values())
        if document_type is not None:
            results = [d for d in results if d.type == document_type]
        if vector_store_id is not None:
            results = [d for d in results if d.vector_store_id == vector_store_id]
        if vector_store_version is not None:
            results = [
                d for d in results if d.vector_store_version == vector_store_version
            ]
        return results


class ScriptedEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def __init__(self) -> None:
        self.embedded_texts: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.embedded_texts.append(list(texts))
        return EmbeddingResult(
            vectors=[[0.1, 0.2, 0.3] for _ in texts],
            model="fake-embedding-model",
            dimensions=3,
        )


class ScriptedEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    def __init__(self) -> None:
        self.operation_names: list[str] = []

    def create(
        self, *, model: str, monitoring: MonitoringPort, operation_name: str
    ) -> EmbeddingUnitOfWork:
        self.operation_names.append(operation_name)
        return ScriptedEmbeddingUnitOfWork()


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


def _taxonomia_input() -> IngestTaxonomiaInput:
    return IngestTaxonomiaInput(
        text="fraude por suplantacion de identidad",
        vector_store_id="vs-1",
        vector_store_version=1,
    )


def test_ingest_taxonomia_embeds_and_creates() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    use_case = IngestTaxonomiaUseCase(
        repository=repository,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )

    created = use_case.execute(_taxonomia_input())

    assert created.type == DocumentType.TAXONOMIA
    assert created.text_embedded == [0.1, 0.2, 0.3]
    assert repository.get(created.id) == created
    assert embedding_factory.operation_names == ["ingest_taxonomia"]


def test_ingest_modus_operandi_requires_existing_taxonomia() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    use_case = IngestModusOperandiUseCase(
        repository=repository,
        embedding_unit_of_work_factory=ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )

    with pytest.raises(ValueError):
        use_case.execute(
            IngestModusOperandiInput(
                text="patron de fraude",
                vector_store_id="vs-1",
                vector_store_version=1,
                taxonomia_id=uuid.uuid4(),
                taxonomia="Suplantacion de identidad",
                library_id="mo-1",
            )
        )


def test_ingest_modus_operandi_succeeds_with_existing_taxonomia() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    taxonomia = IngestTaxonomiaUseCase(
        repository=repository,
        embedding_unit_of_work_factory=ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    ).execute(_taxonomia_input())

    use_case = IngestModusOperandiUseCase(
        repository=repository,
        embedding_unit_of_work_factory=ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )
    created = use_case.execute(
        IngestModusOperandiInput(
            text="patron de fraude",
            vector_store_id="vs-1",
            vector_store_version=1,
            taxonomia_id=taxonomia.id,
            taxonomia="Suplantacion de identidad",
            library_id="mo-1",
        )
    )

    assert created.type == DocumentType.MODUS_OPERANDI
    assert created.taxonomia_id == taxonomia.id
    assert created.similar_cases == []
    assert created.flags == []
    assert created.library_id == "mo-1"


def _seed_taxonomia_and_modus_operandi(
    repository: InMemoryFraudKnowledgeRepository,
) -> ModusOperandiDocument:
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    taxonomia = IngestTaxonomiaUseCase(
        repository=repository,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    ).execute(_taxonomia_input())
    return IngestModusOperandiUseCase(
        repository=repository,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    ).execute(
        IngestModusOperandiInput(
            text="patron de fraude",
            vector_store_id="vs-1",
            vector_store_version=1,
            taxonomia_id=taxonomia.id,
            taxonomia="Suplantacion de identidad",
            library_id="mo-1",
        )
    )


def test_ingest_similar_case_rejects_mismatched_taxonomia() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    modus_operandi = _seed_taxonomia_and_modus_operandi(repository)
    use_case = IngestSimilarCaseUseCase(
        repository=repository,
        embedding_unit_of_work_factory=ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )

    with pytest.raises(ValueError):
        use_case.execute(
            IngestSimilarCaseInput(
                text="caso similar",
                vector_store_id="vs-1",
                vector_store_version=1,
                modus_operandi_id=modus_operandi.id,
                taxonomia_id=uuid.uuid4(),
            )
        )


def test_ingest_similar_case_appends_id_to_parent() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    modus_operandi = _seed_taxonomia_and_modus_operandi(repository)
    use_case = IngestSimilarCaseUseCase(
        repository=repository,
        embedding_unit_of_work_factory=ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )

    created = use_case.execute(
        IngestSimilarCaseInput(
            text="caso similar",
            vector_store_id="vs-1",
            vector_store_version=1,
            modus_operandi_id=modus_operandi.id,
            taxonomia_id=modus_operandi.taxonomia_id,
        )
    )

    updated_parent = repository.get(modus_operandi.id)
    assert isinstance(updated_parent, ModusOperandiDocument)
    assert updated_parent.similar_cases == [created.id]


def test_ingest_flag_appends_id_to_parent() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    modus_operandi = _seed_taxonomia_and_modus_operandi(repository)
    use_case = IngestFlagUseCase(
        repository=repository,
        embedding_unit_of_work_factory=ScriptedEmbeddingUnitOfWorkFactory(),
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )

    created = use_case.execute(
        IngestFlagInput(
            text="senal de alerta roja",
            flag_type=DocumentType.RED_FLAG,
            vector_store_id="vs-1",
            vector_store_version=1,
            modus_operandi_ids=[modus_operandi.id],
        )
    )

    assert created.type == DocumentType.RED_FLAG
    updated_parent = repository.get(modus_operandi.id)
    assert isinstance(updated_parent, ModusOperandiDocument)
    assert updated_parent.flags == [created.id]


def test_ingest_flag_appends_id_to_all_parents_when_many_to_many() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    taxonomia = IngestTaxonomiaUseCase(
        repository=repository,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    ).execute(_taxonomia_input())
    ingest_mo = IngestModusOperandiUseCase(
        repository=repository,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )
    mo_a = ingest_mo.execute(
        IngestModusOperandiInput(
            text="patron A",
            vector_store_id="vs-1",
            vector_store_version=1,
            taxonomia_id=taxonomia.id,
            taxonomia=taxonomia.text,
            library_id="mo-a",
        )
    )
    mo_b = ingest_mo.execute(
        IngestModusOperandiInput(
            text="patron B",
            vector_store_id="vs-1",
            vector_store_version=1,
            taxonomia_id=taxonomia.id,
            taxonomia=taxonomia.text,
            library_id="mo-b",
        )
    )

    use_case = IngestFlagUseCase(
        repository=repository,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )
    created = use_case.execute(
        IngestFlagInput(
            text="senal compartida",
            flag_type=DocumentType.YELLOW_FLAG,
            vector_store_id="vs-1",
            vector_store_version=1,
            modus_operandi_ids=[mo_a.id, mo_b.id],
        )
    )

    updated_a = repository.get(mo_a.id)
    updated_b = repository.get(mo_b.id)
    assert isinstance(updated_a, ModusOperandiDocument)
    assert isinstance(updated_b, ModusOperandiDocument)
    assert updated_a.flags == [created.id]
    assert updated_b.flags == [created.id]
    assert created.modus_operandi_ids == [mo_a.id, mo_b.id]
