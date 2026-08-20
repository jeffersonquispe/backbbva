from __future__ import annotations

from typing import Any
from uuid import UUID

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
    ModusOperandiDocument,
    RedFlagDocument,
    SimilarCaseDocument,
    TaxonomiaDocument,
    YellowFlagDocument,
)
from src.infrastructure.persistence.vector_store.opensearch.index import (
    FRAUD_KNOWLEDGE_INDEX,
)

_DOCUMENT_CLASSES = {
    DocumentType.TAXONOMIA: TaxonomiaDocument,
    DocumentType.MODUS_OPERANDI: ModusOperandiDocument,
    DocumentType.SIMILAR_CASE: SimilarCaseDocument,
    DocumentType.RED_FLAG: RedFlagDocument,
    DocumentType.YELLOW_FLAG: YellowFlagDocument,
}

_PARENTED_TYPES = (SimilarCaseDocument, RedFlagDocument, YellowFlagDocument)


def document_to_source(document: FraudKnowledgeDocument) -> dict[str, Any]:
    source: dict[str, Any] = {
        "type": document.type.value,
        "id": str(document.id),
        "text": document.text,
        "text_embedded": document.text_embedded,
        "segmento": document.segmento,
        "configuration": document.configuration,
        "version": document.version,
        "activate": document.activate,
    }
    if isinstance(document, ModusOperandiDocument):
        source.update(
            taxonomia_id=str(document.taxonomia_id),
            taxonomia=document.taxonomia,
            similar_cases=[str(i) for i in document.similar_cases],
            red_flags=[str(i) for i in document.red_flags],
            yellow_flags=[str(i) for i in document.yellow_flags],
        )
    elif isinstance(document, _PARENTED_TYPES):
        source.update(
            modus_operandi_id=str(document.modus_operandi_id),
            taxonomia_id=str(document.taxonomia_id),
        )
    return source


def document_from_source(source: dict[str, Any]) -> FraudKnowledgeDocument:
    document_type = DocumentType(source["type"])
    document_cls = _DOCUMENT_CLASSES[document_type]
    fields: dict[str, Any] = {
        "id": UUID(source["id"]),
        "text": source["text"],
        "text_embedded": source["text_embedded"],
        "segmento": source["segmento"],
        "configuration": source["configuration"],
        "version": source["version"],
        "activate": source["activate"],
        "type": document_type,
    }
    if document_type == DocumentType.MODUS_OPERANDI:
        fields.update(
            taxonomia_id=UUID(source["taxonomia_id"]),
            taxonomia=source["taxonomia"],
            similar_cases=[UUID(i) for i in source.get("similar_cases", [])],
            red_flags=[UUID(i) for i in source.get("red_flags", [])],
            yellow_flags=[UUID(i) for i in source.get("yellow_flags", [])],
        )
    elif document_type in (
        DocumentType.SIMILAR_CASE,
        DocumentType.RED_FLAG,
        DocumentType.YELLOW_FLAG,
    ):
        fields.update(
            modus_operandi_id=UUID(source["modus_operandi_id"]),
            taxonomia_id=UUID(source["taxonomia_id"]),
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
        channel: str | None = None,
        configuration: str | None = None,
        version: int | None = None,
    ) -> list[FraudKnowledgeDocument]:
        filters: list[dict[str, Any]] = []
        if document_type is not None:
            filters.append({"term": {"type": document_type.value}})
        if channel is not None:
            filters.append({"term": {"segmento": channel}})
        if configuration is not None:
            filters.append({"term": {"configuration": configuration}})
        if version is not None:
            filters.append({"term": {"version": version}})
        query = {"bool": {"filter": filters}} if filters else {"match_all": {}}

        response = self._client.search(
            index=FRAUD_KNOWLEDGE_INDEX,
            body={"query": query, "size": 500},
        )
        return [
            document_from_source(hit["_source"]) for hit in response["hits"]["hits"]
        ]
