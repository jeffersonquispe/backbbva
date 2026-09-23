from __future__ import annotations

from opensearchpy import OpenSearch

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeSearchPort,
    FraudKnowledgeSearchResult,
    SearchPipeline,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.infrastructure.persistence.vector_store.opensearch.index import (
    FRAUD_KNOWLEDGE_INDEX,
)
from src.infrastructure.persistence.vector_store.opensearch.repository import (
    document_from_source,
)


class OpenSearchFraudKnowledgeSearchAdapter(FraudKnowledgeSearchPort):
    def __init__(
        self,
        client: OpenSearch,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
    ) -> None:
        self._client = client
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model

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
        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="fraud_knowledge_search",
        )
        vector = uow.embed([query]).vectors[0]

        filter_clauses = [
            {"term": {"vector_store_id": vector_store_id}},
            {"term": {"vector_store_version": vector_store_version}},
            {"term": {"type": document_type.value}},
        ]

        # kNN "filter" requires an engine that supports efficient
        # pre-filtering (faiss, per index.py's mapping).
        body = {
            "query": {
                "hybrid": {
                    "queries": [
                        {
                            "bool": {
                                "must": [{"match": {"text": query}}],
                                "filter": filter_clauses,
                            }
                        },
                        {
                            "knn": {
                                "text_embedded": {
                                    "vector": vector,
                                    "k": top_k,
                                    "filter": {"bool": {"filter": filter_clauses}},
                                }
                            }
                        },
                    ]
                }
            },
            "size": top_k,
        }

        response = self._client.search(
            index=FRAUD_KNOWLEDGE_INDEX,
            body=body,
            params={"search_pipeline": pipeline.value},
        )
        return [
            FraudKnowledgeSearchResult(
                document=document_from_source(hit["_source"]),
                score=hit["_score"],
            )
            for hit in response["hits"]["hits"]
        ]
