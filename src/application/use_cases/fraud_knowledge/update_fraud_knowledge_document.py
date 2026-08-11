from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.fraud_knowledge_port import FraudKnowledgeDocument
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.monitoring_port import MonitoringPort


@dataclass(frozen=True)
class UpdateFraudKnowledgeDocumentInput:
    document_id: UUID
    text: str | None = None
    segmento: str | None = None
    configuration: str | None = None
    version: int | None = None
    activate: bool | None = None


class UpdateFraudKnowledgeDocumentUseCase:
    """Generic across all 5 document types. FK/parentage fields
    (taxonomia_id, modus_operandi_id, similar_cases/red_flags/yellow_flags)
    are immutable here — re-parenting isn't supported."""

    def __init__(
        self,
        repository: FraudKnowledgeRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
    ) -> None:
        self._repository = repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model

    def execute(
        self, data: UpdateFraudKnowledgeDocumentInput
    ) -> FraudKnowledgeDocument:
        document = self._repository.get(data.document_id)
        if document is None:
            raise ValueError(f"document {data.document_id} not found")

        updates: dict[str, Any] = {}
        if data.segmento is not None:
            updates["segmento"] = data.segmento
        if data.configuration is not None:
            updates["configuration"] = data.configuration
        if data.version is not None:
            updates["version"] = data.version
        if data.activate is not None:
            updates["activate"] = data.activate
        if data.text is not None and data.text != document.text:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="update_fraud_knowledge_document",
            )
            embedding = uow.embed([data.text])
            updates["text"] = data.text
            updates["text_embedded"] = embedding.vectors[0]

        return self._repository.update(replace(document, **updates))
