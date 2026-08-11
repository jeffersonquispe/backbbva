from __future__ import annotations

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)


class ListFraudKnowledgeDocumentsUseCase:
    def __init__(self, repository: FraudKnowledgeRepository) -> None:
        self._repository = repository

    def execute(
        self,
        document_type: DocumentType | None = None,
        *,
        channel: str | None = None,
    ) -> list[FraudKnowledgeDocument]:
        return self._repository.list(document_type, channel=channel)
