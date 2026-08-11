from __future__ import annotations

import uuid

from src.application.ports.embedding_port import (
    EmbeddingResult,
    EmbeddingUnitOfWork,
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
    TaxonomiaDocument,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.use_cases.fraud_knowledge.update_fraud_knowledge_document import (
    UpdateFraudKnowledgeDocumentInput,
    UpdateFraudKnowledgeDocumentUseCase,
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
        channel: str | None = None,
    ) -> list[FraudKnowledgeDocument]:
        return list(self._documents.values())


class ScriptedEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def __init__(self) -> None:
        self.embedded_texts: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.embedded_texts.append(list(texts))
        return EmbeddingResult(
            vectors=[[0.9, 0.9, 0.9] for _ in texts],
            model="fake-embedding-model",
            dimensions=3,
        )


class ScriptedEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    def __init__(self) -> None:
        self.uows: list[ScriptedEmbeddingUnitOfWork] = []

    def create(
        self, *, model: str, monitoring: MonitoringPort, operation_name: str
    ) -> EmbeddingUnitOfWork:
        uow = ScriptedEmbeddingUnitOfWork()
        self.uows.append(uow)
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


def _seed_taxonomia(repository: InMemoryFraudKnowledgeRepository) -> TaxonomiaDocument:
    document = TaxonomiaDocument(
        id=uuid.uuid4(),
        text="fraude por suplantacion de identidad",
        text_embedded=[0.1, 0.1, 0.1],
        segmento="tarjetas",
        configuration="default",
        version=1,
    )
    return repository.create(document)


def test_update_without_text_change_does_not_reembed() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    taxonomia = _seed_taxonomia(repository)
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    use_case = UpdateFraudKnowledgeDocumentUseCase(
        repository=repository,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )

    updated = use_case.execute(
        UpdateFraudKnowledgeDocumentInput(document_id=taxonomia.id, activate=False)
    )

    assert updated.activate is False
    assert updated.text_embedded == taxonomia.text_embedded
    assert embedding_factory.uows == []


def test_update_with_changed_text_reembeds() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    taxonomia = _seed_taxonomia(repository)
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    use_case = UpdateFraudKnowledgeDocumentUseCase(
        repository=repository,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=NullMonitoringPort(),
        embedding_model="fake-deployment",
    )

    updated = use_case.execute(
        UpdateFraudKnowledgeDocumentInput(
            document_id=taxonomia.id, text="nuevo texto de taxonomia"
        )
    )

    assert updated.text == "nuevo texto de taxonomia"
    assert updated.text_embedded == [0.9, 0.9, 0.9]
    assert len(embedding_factory.uows) == 1
