from __future__ import annotations

import uuid

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
from src.application.use_cases.fraud_knowledge.get_related_fraud_knowledge import (
    GetRelatedFraudKnowledgeUseCase,
)
from src.application.use_cases.fraud_knowledge.list_fraud_knowledge_documents import (
    ListFraudKnowledgeDocumentsUseCase,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
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
        channel: str | None = None,
    ) -> list[FraudKnowledgeDocument]:
        results = self._documents
        if document_type is not None:
            results = [d for d in results if d.type == document_type]
        if channel is not None:
            results = [d for d in results if d.segmento == channel]
        return results


class RecordingFraudKnowledgeSearchPort(FraudKnowledgeSearchPort):
    def __init__(self, result: FraudKnowledgeSearchResult) -> None:
        self._result = result
        self.calls: list[dict] = []

    def search(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        channel: str,
        document_type: DocumentType,
        top_k: int = 5,
    ) -> list[FraudKnowledgeSearchResult]:
        self.calls.append(
            {
                "query": query,
                "pipeline": pipeline,
                "channel": channel,
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
        segmento="tarjetas",
        configuration="default",
        version=1,
    )


def test_list_fraud_knowledge_documents_delegates_to_repository() -> None:
    taxonomia = _taxonomia()
    repository = InMemoryFraudKnowledgeRepository([taxonomia])

    results = ListFraudKnowledgeDocumentsUseCase(repository).execute(
        DocumentType.TAXONOMIA, channel="tarjetas"
    )

    assert results == [taxonomia]


def test_search_fraud_knowledge_delegates_to_search_port() -> None:
    taxonomia = _taxonomia()
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(document=taxonomia, score=0.87)
    )

    results = SearchFraudKnowledgeUseCase(search_port).execute(
        "suplantacion de identidad",
        pipeline=SearchPipeline.BALANCED,
        channel="tarjetas",
        document_type=DocumentType.TAXONOMIA,
        top_k=3,
    )

    assert results == [FraudKnowledgeSearchResult(document=taxonomia, score=0.87)]
    assert search_port.calls == [
        {
            "query": "suplantacion de identidad",
            "pipeline": SearchPipeline.BALANCED,
            "channel": "tarjetas",
            "document_type": DocumentType.TAXONOMIA,
            "top_k": 3,
        }
    ]


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
