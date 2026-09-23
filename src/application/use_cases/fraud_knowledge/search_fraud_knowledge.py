from __future__ import annotations

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeSearchPort,
    FraudKnowledgeSearchResult,
    SearchPipeline,
)
from src.application.ports.vector_store_instance_port import (
    VectorStoreInstanceRepository,
)


class VectorStoreNotPromotedError(ValueError):
    pass


class SearchFraudKnowledgeUseCase:
    """Resolves the vector store's current promoted generation and searches
    only that generation - never a stale one left behind mid-promotion, and
    never across every generation ever loaded for this vector_store_id."""

    def __init__(
        self,
        search_port: FraudKnowledgeSearchPort,
        instances: VectorStoreInstanceRepository,
    ) -> None:
        self._search_port = search_port
        self._instances = instances

    def execute(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        vector_store_id: str,
        document_type: DocumentType,
        top_k: int = 5,
    ) -> list[FraudKnowledgeSearchResult]:
        instance = self._instances.get(vector_store_id)
        if instance is None or instance.promoted_version is None:
            raise VectorStoreNotPromotedError(
                f"vector store {vector_store_id} has not been promoted to production"
            )
        return self._search_port.search(
            query,
            pipeline=pipeline,
            vector_store_id=vector_store_id,
            vector_store_version=instance.promoted_version,
            document_type=document_type,
            top_k=top_k,
        )
