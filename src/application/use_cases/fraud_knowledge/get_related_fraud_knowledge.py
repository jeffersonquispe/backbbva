from __future__ import annotations

from uuid import UUID

from src.application.ports.fraud_knowledge_port import DocumentType
from src.application.ports.fraud_knowledge_relations_port import (
    FraudKnowledgeRelationsPort,
    RelatedDocumentsResult,
)


class GetRelatedFraudKnowledgeUseCase:
    def __init__(self, relations_port: FraudKnowledgeRelationsPort) -> None:
        self._relations_port = relations_port

    def execute(
        self, document_id: UUID, document_type: DocumentType
    ) -> RelatedDocumentsResult:
        return self._relations_port.get_related(document_id, document_type)
