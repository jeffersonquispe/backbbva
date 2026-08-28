from __future__ import annotations

from uuid import UUID

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FlagDocument,
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
        for child_id in (*document.similar_cases, *document.flags):
            child = self._repository.get(child_id)
            if child is not None:
                related.append(child)
        return related

    def _related_to_flag_or_case(
        self, document: FraudKnowledgeDocument
    ) -> list[FraudKnowledgeDocument]:
        if isinstance(document, FlagDocument):
            return self._related_to_flag(document)
        return self._related_to_similar_case(document)

    def _related_to_similar_case(
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

        for sibling_id in (*parent.similar_cases, *parent.flags):
            if sibling_id == document.id:
                continue
            sibling = self._repository.get(sibling_id)
            if sibling is not None:
                related.append(sibling)
        return related

    def _related_to_flag(self, document: FlagDocument) -> list[FraudKnowledgeDocument]:
        # A flag can have multiple parent modus operandi (M2M) - collect
        # every parent, every parent's taxonomia (deduped), and every
        # parent's siblings (deduped, since two parents can share one).
        related: list[FraudKnowledgeDocument] = []
        seen_ids: set[UUID] = set()

        def _add(doc: FraudKnowledgeDocument | None) -> None:
            if doc is not None and doc.id not in seen_ids:
                seen_ids.add(doc.id)
                related.append(doc)

        for mo_id in document.modus_operandi_ids:
            parent = self._repository.get(mo_id)
            if parent is None or parent.type != DocumentType.MODUS_OPERANDI:
                continue
            assert isinstance(parent, ModusOperandiDocument)
            _add(parent)
            _add(self._repository.get(parent.taxonomia_id))
            for sibling_id in (*parent.similar_cases, *parent.flags):
                if sibling_id == document.id:
                    continue
                _add(self._repository.get(sibling_id))
        return related
