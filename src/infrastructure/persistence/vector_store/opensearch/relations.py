from __future__ import annotations

from uuid import UUID

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
    ModusOperandiDocument,
)
from src.application.ports.fraud_knowledge_relations_port import (
    FraudKnowledgeRelationsPort,
    RelatedDocumentsResult,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)


class OpenSearchFraudKnowledgeRelationsAdapter(FraudKnowledgeRelationsPort):
    def __init__(self, repository: FraudKnowledgeRepository) -> None:
        self._repository = repository

    def get_related(
        self, document_id: UUID, document_type: DocumentType
    ) -> RelatedDocumentsResult:
        document = self._repository.get(document_id)
        if document is None or document.type != document_type:
            raise ValueError(f"{document_type} {document_id} not found")

        if document_type == DocumentType.TAXONOMIA:
            related = self._children_of_taxonomia(document_id)
        elif document_type == DocumentType.MODUS_OPERANDI:
            assert isinstance(document, ModusOperandiDocument)
            related = self._related_to_modus_operandi(document)
        else:
            related = self._related_to_flag_or_case(document)

        return RelatedDocumentsResult(
            origin_id=document_id, origin_type=document_type, related=related
        )

    def _children_of_taxonomia(
        self, taxonomia_id: UUID
    ) -> list[FraudKnowledgeDocument]:
        return [
            doc
            for doc in self._repository.list(DocumentType.MODUS_OPERANDI)
            if doc.taxonomia_id == taxonomia_id
        ]

    def _related_to_modus_operandi(
        self, document: ModusOperandiDocument
    ) -> list[FraudKnowledgeDocument]:
        related: list[FraudKnowledgeDocument] = []
        taxonomia = self._repository.get(document.taxonomia_id)
        if taxonomia is not None:
            related.append(taxonomia)
        for child_id in (
            *document.similar_cases,
            *document.red_flags,
            *document.yellow_flags,
        ):
            child = self._repository.get(child_id)
            if child is not None:
                related.append(child)
        return related

    def _related_to_flag_or_case(
        self, document: FraudKnowledgeDocument
    ) -> list[FraudKnowledgeDocument]:
        related: list[FraudKnowledgeDocument] = []
        taxonomia = self._repository.get(document.taxonomia_id)
        if taxonomia is not None:
            related.append(taxonomia)

        parent = self._repository.get(document.modus_operandi_id)
        if parent is None or parent.type != DocumentType.MODUS_OPERANDI:
            return related
        assert isinstance(parent, ModusOperandiDocument)
        related.append(parent)

        sibling_ids = (
            *parent.similar_cases,
            *parent.red_flags,
            *parent.yellow_flags,
        )
        for sibling_id in sibling_ids:
            if sibling_id == document.id:
                continue
            sibling = self._repository.get(sibling_id)
            if sibling is not None:
                related.append(sibling)
        return related
