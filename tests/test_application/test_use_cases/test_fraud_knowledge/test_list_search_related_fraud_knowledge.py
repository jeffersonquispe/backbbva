from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
    FraudKnowledgeSearchPort,
    FraudKnowledgeSearchResult,
    SearchPipeline,
    TaxonomiaDocument,
)
from src.application.ports.fraud_knowledge_relations_port import (
    FraudKnowledgeRelationsPort,
    RelatedDocumentsResult,
)
from src.application.ports.vector_store_generation_port import (
    VectorStoreGeneration,
    VectorStoreGenerationStatus,
)
from src.application.use_cases.fraud_knowledge.get_related_fraud_knowledge import (
    GetRelatedFraudKnowledgeUseCase,
)
from src.application.use_cases.fraud_knowledge.list_fraud_knowledge_documents import (
    ListFraudKnowledgeDocumentsUseCase,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
    VectorStoreGenerationUnavailableError,
)


class InMemoryFraudKnowledgeRepository:
    def __init__(self, documents: list[FraudKnowledgeDocument]) -> None:
        self._documents = documents

    def create(self, document):
        raise NotImplementedError

    def get(self, document_id):
        raise NotImplementedError

    def update(self, document):
        raise NotImplementedError

    def delete(self, document_id) -> None:
        raise NotImplementedError

    def list(
        self,
        document_type: DocumentType | None = None,
        *,
        vector_store_id: str | None = None,
        vector_store_version: int | None = None,
    ) -> list[FraudKnowledgeDocument]:
        results = self._documents
        if document_type is not None:
            results = [d for d in results if d.type == document_type]
        if vector_store_id is not None:
            results = [d for d in results if d.vector_store_id == vector_store_id]
        return results


class InMemoryVectorStoreGenerationRepository:
    def __init__(self, generations):
        self.items = {(g.instance_id, g.generation): g for g in generations}

    def get(self, instance_id, generation):
        return self.items.get((instance_id, generation))

    def list(self, instance_id=None):
        return sorted([g for g in self.items.values() if instance_id is None or g.instance_id == instance_id], key=lambda g: g.generation)


def _ready_generation(instance_id: str = "vs-1", version: int = 1):
    return VectorStoreGeneration(instance_id=instance_id, generation=version,
        status=VectorStoreGenerationStatus.READY, built_by="tester", created_at=datetime.now(UTC))


class RecordingFraudKnowledgeSearchPort(FraudKnowledgeSearchPort):
    def __init__(self, result: FraudKnowledgeSearchResult) -> None:
        self._result = result
        self.calls: list[dict] = []

    def search(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        vector_store_id: str,
        vector_store_version: int,
        document_type: DocumentType,
        top_k: int = 5,
    ) -> list[FraudKnowledgeSearchResult]:
        self.calls.append(
            {
                "query": query,
                "pipeline": pipeline,
                "vector_store_id": vector_store_id,
                "vector_store_version": vector_store_version,
                "document_type": document_type,
                "top_k": top_k,
            }
        )
        return [self._result]


class RecordingFraudKnowledgeRelationsPort(FraudKnowledgeRelationsPort):
    def __init__(self, result: RelatedDocumentsResult) -> None:
        self._result = result
        self.calls: list[tuple[uuid.UUID, DocumentType]] = []

    def get_related(
        self, document_id: uuid.UUID, document_type: DocumentType
    ) -> RelatedDocumentsResult:
        self.calls.append((document_id, document_type))
        return self._result


def _taxonomia() -> TaxonomiaDocument:
    return TaxonomiaDocument(
        id=uuid.uuid4(),
        text="taxonomia",
        text_embedded=[0.1],
        vector_store_id="vs-1",
        vector_store_version=1,
    )


def test_list_fraud_knowledge_documents_delegates_to_repository() -> None:
    taxonomia = _taxonomia()
    repository = InMemoryFraudKnowledgeRepository([taxonomia])

    results = ListFraudKnowledgeDocumentsUseCase(repository).execute(
        DocumentType.TAXONOMIA, vector_store_id="vs-1"
    )

    assert results == [taxonomia]


def test_search_fraud_knowledge_resolves_current_version_and_delegates_to_search_port() -> (
    None
):
    taxonomia = _taxonomia()
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(document=taxonomia, score=0.87)
    )
    instances = InMemoryVectorStoreGenerationRepository(
        [_ready_generation("vs-1", version=3)]
    )

    results = SearchFraudKnowledgeUseCase(search_port, instances).execute(
        "suplantacion de identidad",
        pipeline=SearchPipeline.BALANCED,
        vector_store_id="vs-1",
        document_type=DocumentType.TAXONOMIA,
        top_k=3,
    )

    assert results == [FraudKnowledgeSearchResult(document=taxonomia, score=0.87)]
    assert search_port.calls == [
        {
            "query": "suplantacion de identidad",
            "pipeline": SearchPipeline.BALANCED,
            "vector_store_id": "vs-1",
            "vector_store_version": 3,
            "document_type": DocumentType.TAXONOMIA,
            "top_k": 3,
        }
    ]


def test_search_fraud_knowledge_rejects_unpromoted_vector_store() -> None:
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(document=_taxonomia(), score=0.5)
    )
    instances = InMemoryVectorStoreGenerationRepository([])

    try:
        SearchFraudKnowledgeUseCase(search_port, instances).execute(
            "query",
            pipeline=SearchPipeline.BALANCED,
            vector_store_id="vs-missing",
            document_type=DocumentType.TAXONOMIA,
        )
    except VectorStoreGenerationUnavailableError:
        pass
    else:
        raise AssertionError("expected VectorStoreGenerationUnavailableError")
    assert search_port.calls == []


def test_get_related_fraud_knowledge_delegates_to_relations_port() -> None:
    taxonomia = _taxonomia()
    document_id = uuid.uuid4()
    relations_port = RecordingFraudKnowledgeRelationsPort(
        RelatedDocumentsResult(
            origin_id=document_id,
            origin_type=DocumentType.MODUS_OPERANDI,
            related=[taxonomia],
        )
    )

    result = GetRelatedFraudKnowledgeUseCase(relations_port).execute(
        document_id, DocumentType.MODUS_OPERANDI
    )

    assert result.origin_id == document_id
    assert result.related == [taxonomia]
    assert relations_port.calls == [(document_id, DocumentType.MODUS_OPERANDI)]
