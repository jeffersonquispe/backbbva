from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeSearchPort,
    FraudKnowledgeSearchResult,
    ModusOperandiDocument,
    SearchPipeline,
    SimilarCaseDocument,
    TaxonomiaDocument,
)
from src.application.ports.fraud_similarity_port import SimilarFraudCase
from src.application.ports.fraud_taxonomy_port import SimilarFraudTaxonomy
from src.application.ports.modus_operandi_port import SimilarModusOperandi
from src.application.ports.vector_store_instance_port import VectorStoreInstance
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)
from src.infrastructure.fraud_intelligence.opensearch.fraud_taxonomy_adapter import (
    OpenSearchFraudTaxonomyAdapter,
)
from src.infrastructure.fraud_intelligence.opensearch.modus_operandi_adapter import (
    OpenSearchModusOperandiAdapter,
)
from src.infrastructure.fraud_intelligence.opensearch.similar_fraud_case_adapter import (
    OpenSearchSimilarFraudCaseAdapter,
)


class InMemoryVectorStoreInstanceRepository:
    def __init__(self, instances: list[VectorStoreInstance]) -> None:
        self._instances = {instance.id: instance for instance in instances}

    def create(self, instance, assets):
        raise NotImplementedError

    def list(self):
        return list(self._instances.values())

    def get(self, instance_id: str) -> VectorStoreInstance | None:
        return self._instances.get(instance_id)

    def update(self, instance):
        raise NotImplementedError

    def list_assets(self, instance_id: str):
        raise NotImplementedError

    def add_asset(self, asset):
        raise NotImplementedError

    def remove_asset(self, instance_id, relation_id) -> None:
        raise NotImplementedError


def _promoted_instance(instance_id: str = "vs-1", version: int = 1) -> VectorStoreInstance:
    return VectorStoreInstance(
        id=instance_id,
        version=1,
        name="Instancia",
        description="",
        created_at=datetime.now(timezone.utc),
        created_by="tester",
        promoted_version=version,
    )


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


def test_fraud_taxonomy_adapter_maps_search_result_and_scopes_the_call() -> None:
    taxonomia_id = uuid.uuid4()
    document = TaxonomiaDocument(
        id=taxonomia_id,
        text="Suplantación de identidad: uso no autorizado de datos personales",
        text_embedded=[0.1],
        vector_store_id="vs-1",
        vector_store_version=2,
    )
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(document=document, score=0.91)
    )
    use_case = SearchFraudKnowledgeUseCase(
        search_port, InMemoryVectorStoreInstanceRepository([_promoted_instance("vs-1", version=2)])
    )
    adapter = OpenSearchFraudTaxonomyAdapter(use_case, "vs-1")

    results = adapter.find_similar("suplantación", top_k=3)

    assert results == [
        SimilarFraudTaxonomy(
            code=str(taxonomia_id),
            name=document.text,
            description=document.text,
            similarity_score=0.91,
        )
    ]
    assert search_port.calls == [
        {
            "query": "suplantación",
            "pipeline": SearchPipeline.BALANCED,
            "vector_store_id": "vs-1",
            "vector_store_version": 2,
            "document_type": DocumentType.TAXONOMIA,
            "top_k": 3,
        }
    ]


def test_fraud_taxonomy_adapter_fails_open_when_vector_store_not_promoted() -> None:
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(
            document=TaxonomiaDocument(
                id=uuid.uuid4(), text="x", text_embedded=[0.0], vector_store_id="vs-1", vector_store_version=1
            ),
            score=0.5,
        )
    )
    use_case = SearchFraudKnowledgeUseCase(search_port, InMemoryVectorStoreInstanceRepository([]))
    adapter = OpenSearchFraudTaxonomyAdapter(use_case, "vs-missing")

    assert adapter.find_similar("query") == []
    assert search_port.calls == []


def test_modus_operandi_adapter_maps_search_result() -> None:
    mo_id = uuid.uuid4()
    document = ModusOperandiDocument(
        id=mo_id,
        text="Cambio de datos personales seguido de transferencia",
        text_embedded=[0.2],
        vector_store_id="vs-1",
        vector_store_version=1,
        taxonomia_id=uuid.uuid4(),
        taxonomia="Suplantación",
        similar_cases=[],
        flags=[],
    )
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(document=document, score=0.77)
    )
    use_case = SearchFraudKnowledgeUseCase(
        search_port, InMemoryVectorStoreInstanceRepository([_promoted_instance("vs-1", version=1)])
    )
    adapter = OpenSearchModusOperandiAdapter(use_case, "vs-1")

    results = adapter.find_similar("cambio de datos", top_k=2)

    assert results == [
        SimilarModusOperandi(
            pattern_id=str(mo_id), description=document.text, similarity_score=0.77
        )
    ]
    assert search_port.calls[0]["document_type"] == DocumentType.MODUS_OPERANDI
    assert search_port.calls[0]["top_k"] == 2


def test_modus_operandi_adapter_fails_open_when_vector_store_not_promoted() -> None:
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(
            document=ModusOperandiDocument(
                id=uuid.uuid4(),
                text="x",
                text_embedded=[0.0],
                vector_store_id="vs-1",
                vector_store_version=1,
                taxonomia_id=uuid.uuid4(),
                taxonomia="",
                similar_cases=[],
                flags=[],
            ),
            score=0.5,
        )
    )
    use_case = SearchFraudKnowledgeUseCase(search_port, InMemoryVectorStoreInstanceRepository([]))
    adapter = OpenSearchModusOperandiAdapter(use_case, "vs-missing")

    assert adapter.find_similar("query") == []
    assert search_port.calls == []


def test_similar_fraud_case_adapter_maps_search_result_with_blank_outcome() -> None:
    case_id = uuid.uuid4()
    document = SimilarCaseDocument(
        id=case_id,
        text="Cambio de dispositivo seguido de transferencia de alto valor",
        text_embedded=[0.3],
        vector_store_id="vs-1",
        vector_store_version=1,
        modus_operandi_id=uuid.uuid4(),
        taxonomia_id=uuid.uuid4(),
    )
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(document=document, score=0.83)
    )
    use_case = SearchFraudKnowledgeUseCase(
        search_port, InMemoryVectorStoreInstanceRepository([_promoted_instance("vs-1", version=1)])
    )
    adapter = OpenSearchSimilarFraudCaseAdapter(use_case, "vs-1")

    results = adapter.find_similar("dispositivo nuevo")

    assert results == [
        SimilarFraudCase(
            case_id=str(case_id), summary=document.text, outcome="", similarity_score=0.83
        )
    ]
    assert search_port.calls[0]["document_type"] == DocumentType.SIMILAR_CASE


def test_similar_fraud_case_adapter_fails_open_when_vector_store_not_promoted() -> None:
    search_port = RecordingFraudKnowledgeSearchPort(
        FraudKnowledgeSearchResult(
            document=SimilarCaseDocument(
                id=uuid.uuid4(),
                text="x",
                text_embedded=[0.0],
                vector_store_id="vs-1",
                vector_store_version=1,
                modus_operandi_id=uuid.uuid4(),
                taxonomia_id=uuid.uuid4(),
            ),
            score=0.5,
        )
    )
    use_case = SearchFraudKnowledgeUseCase(search_port, InMemoryVectorStoreInstanceRepository([]))
    adapter = OpenSearchSimilarFraudCaseAdapter(use_case, "vs-missing")

    assert adapter.find_similar("query") == []
    assert search_port.calls == []
