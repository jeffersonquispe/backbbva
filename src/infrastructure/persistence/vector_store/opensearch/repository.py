from __future__ import annotations

from typing import Any
from uuid import UUID

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FlagDocument,
    FraudKnowledgeDocument,
    ModusOperandiDocument,
    SimilarCaseDocument,
    TaxonomiaDocument,
)
from src.infrastructure.persistence.vector_store.opensearch.index import (
    FRAUD_KNOWLEDGE_INDEX,
)

_DOCUMENT_CLASSES = {
    DocumentType.TAXONOMIA: TaxonomiaDocument,
    DocumentType.MODUS_OPERANDI: ModusOperandiDocument,
    DocumentType.SIMILAR_CASE: SimilarCaseDocument,
    DocumentType.RED_FLAG: FlagDocument,
    DocumentType.YELLOW_FLAG: FlagDocument,
}


def document_to_source(document: FraudKnowledgeDocument) -> dict[str, Any]:
    source: dict[str, Any] = {
        "type": document.type.value,
        "id": str(document.id),
        "text": document.text,
        "text_embedded": document.text_embedded,
        "vector_store_id": document.vector_store_id,
        "vector_store_version": document.vector_store_version,
    }
    if isinstance(document, ModusOperandiDocument):
        source.update(
            taxonomia_id=str(document.taxonomia_id),
            taxonomia=document.taxonomia,
            similar_cases=[str(i) for i in document.similar_cases],
            flags=[str(i) for i in document.flags],
            library_id=document.library_id,
        )
    elif isinstance(document, SimilarCaseDocument):
        source.update(
            modus_operandi_id=str(document.modus_operandi_id),
            taxonomia_id=str(document.taxonomia_id),
        )
    elif isinstance(document, FlagDocument):
        source.update(
            modus_operandi_ids=[str(i) for i in document.modus_operandi_ids],
        )
    return source


def document_from_source(source: dict[str, Any]) -> FraudKnowledgeDocument:
    document_type = DocumentType(source["type"])
    document_cls = _DOCUMENT_CLASSES[document_type]
    fields: dict[str, Any] = {
        "id": UUID(source["id"]),
        "text": source["text"],
        "text_embedded": source["text_embedded"],
        "vector_store_id": source["vector_store_id"],
        "vector_store_version": source["vector_store_version"],
        "type": document_type,
    }
    if document_type == DocumentType.MODUS_OPERANDI:
        fields.update(
            taxonomia_id=UUID(source["taxonomia_id"]),
            taxonomia=source["taxonomia"],
            similar_cases=[UUID(i) for i in source.get("similar_cases", [])],
            flags=[UUID(i) for i in source.get("flags", [])],
            # .get() default, not source["library_id"] - documents indexed
            # before this field existed lack it (see ModusOperandiDocument's
            # docstring); this path also runs during a promotion's own
            # delete-previous-generation list() call, which must not crash
            # on an old-generation document.
            library_id=source.get("library_id", ""),
        )
    elif document_type == DocumentType.SIMILAR_CASE:
        fields.update(
            modus_operandi_id=UUID(source["modus_operandi_id"]),
            taxonomia_id=UUID(source["taxonomia_id"]),
        )
    elif document_type in (DocumentType.RED_FLAG, DocumentType.YELLOW_FLAG):
        fields.update(
            modus_operandi_ids=[UUID(i) for i in source.get("modus_operandi_ids", [])],
        )
    return document_cls(**fields)


class OpenSearchFraudKnowledgeRepository:
    def __init__(self, client: OpenSearch) -> None:
        self._client = client

    def create(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._client.index(
            index=FRAUD_KNOWLEDGE_INDEX,
            id=str(document.id),
            body=document_to_source(document),
            refresh=True,
        )
        return document

    def get(self, document_id: UUID) -> FraudKnowledgeDocument | None:
        try:
            response = self._client.get(
                index=FRAUD_KNOWLEDGE_INDEX, id=str(document_id)
            )
        except NotFoundError:
            return None
        return document_from_source(response["_source"])

    def update(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._client.index(
            index=FRAUD_KNOWLEDGE_INDEX,
            id=str(document.id),
            body=document_to_source(document),
            refresh=True,
        )
        return document

    def delete(self, document_id: UUID) -> None:
        try:
            self._client.delete(
                index=FRAUD_KNOWLEDGE_INDEX, id=str(document_id), refresh=True
            )
        except NotFoundError:
            pass

    def list(
        self,
        document_type: DocumentType | None = None,
        *,
        vector_store_id: str | None = None,
        vector_store_version: int | None = None,
    ) -> list[FraudKnowledgeDocument]:
        filters: list[dict[str, Any]] = []
        if document_type is not None:
            filters.append({"term": {"type": document_type.value}})
        if vector_store_id is not None:
            filters.append({"term": {"vector_store_id": vector_store_id}})
        if vector_store_version is not None:
            filters.append({"term": {"vector_store_version": vector_store_version}})
        query = {"bool": {"filter": filters}} if filters else {"match_all": {}}

        response = self._client.search(
            index=FRAUD_KNOWLEDGE_INDEX,
            body={"query": query, "size": 500},
        )
        return [
            document_from_source(hit["_source"]) for hit in response["hits"]["hits"]
        ]
