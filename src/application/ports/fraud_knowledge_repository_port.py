from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
)


class FraudKnowledgeRepository(Protocol):
    """Dumb CRUD persistence for fraud knowledge documents. No referential
    integrity or cascade logic here — that's application-layer business
    logic, see `application/use_cases/fraud_knowledge/`."""

    def create(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument: ...

    def get(self, document_id: UUID) -> FraudKnowledgeDocument | None: ...

    def update(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument: ...

    def delete(self, document_id: UUID) -> None: ...

    def list(
        self,
        document_type: DocumentType | None = None,
        *,
        channel: str | None = None,
        configuration: str | None = None,
        version: int | None = None,
    ) -> list[FraudKnowledgeDocument]: ...
