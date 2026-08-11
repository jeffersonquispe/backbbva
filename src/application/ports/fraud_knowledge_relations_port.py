from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
)


@dataclass(frozen=True)
class RelatedDocumentsResult:
    origin_id: UUID
    origin_type: DocumentType
    related: list[FraudKnowledgeDocument]


class FraudKnowledgeRelationsPort(ABC):
    """Traverses the taxonomia -> modus_operandi -> {similar_case, red_flag,
    yellow_flag} relation graph from any origin document."""

    @abstractmethod
    def get_related(
        self, document_id: UUID, document_type: DocumentType
    ) -> RelatedDocumentsResult: ...
