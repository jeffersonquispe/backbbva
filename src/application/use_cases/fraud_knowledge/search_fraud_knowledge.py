from __future__ import annotations

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeSearchPort,
    FraudKnowledgeSearchResult,
    SearchPipeline,
)


class SearchFraudKnowledgeUseCase:
    def __init__(self, search_port: FraudKnowledgeSearchPort) -> None:
        self._search_port = search_port

    def execute(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        channel: str,
        document_type: DocumentType,
        top_k: int = 5,
    ) -> list[FraudKnowledgeSearchResult]:
        return self._search_port.search(
            query,
            pipeline=pipeline,
            channel=channel,
            document_type=document_type,
            top_k=top_k,
        )
