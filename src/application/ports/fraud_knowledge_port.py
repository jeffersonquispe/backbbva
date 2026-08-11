from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class DocumentType(StrEnum):
    TAXONOMIA = "taxonomia"
    MODUS_OPERANDI = "modus_operandi"
    SIMILAR_CASE = "similar_case"
    RED_FLAG = "red_flag"
    YELLOW_FLAG = "yellow_flag"


@dataclass(frozen=True)
class TaxonomiaDocument:
    id: UUID
    text: str
    text_embedded: list[float]
    segmento: str
    configuration: str
    version: int
    activate: bool = True
    type: DocumentType = DocumentType.TAXONOMIA


@dataclass(frozen=True)
class ModusOperandiDocument:
    id: UUID
    text: str
    text_embedded: list[float]
    segmento: str
    configuration: str
    version: int
    taxonomia_id: UUID
    taxonomia: str
    similar_cases: list[UUID]
    red_flags: list[UUID]
    yellow_flags: list[UUID]
    activate: bool = True
    type: DocumentType = DocumentType.MODUS_OPERANDI


@dataclass(frozen=True)
class SimilarCaseDocument:
    id: UUID
    text: str
    text_embedded: list[float]
    segmento: str
    configuration: str
    version: int
    modus_operandi_id: UUID
    taxonomia_id: UUID
    activate: bool = True
    type: DocumentType = DocumentType.SIMILAR_CASE


@dataclass(frozen=True)
class RedFlagDocument:
    id: UUID
    text: str
    text_embedded: list[float]
    segmento: str
    configuration: str
    version: int
    modus_operandi_id: UUID
    taxonomia_id: UUID
    activate: bool = True
    type: DocumentType = DocumentType.RED_FLAG


@dataclass(frozen=True)
class YellowFlagDocument:
    id: UUID
    text: str
    text_embedded: list[float]
    segmento: str
    configuration: str
    version: int
    modus_operandi_id: UUID
    taxonomia_id: UUID
    activate: bool = True
    type: DocumentType = DocumentType.YELLOW_FLAG


FraudKnowledgeDocument = (
    TaxonomiaDocument
    | ModusOperandiDocument
    | SimilarCaseDocument
    | RedFlagDocument
    | YellowFlagDocument
)


class SearchPipeline(StrEnum):
    """Value doubles as the OpenSearch search_pipeline id."""

    EMBEDDING_HEAVY = "fraud_knowledge_hybrid_80_20"  # 0.8 embedding / 0.2 keyword
    BALANCED = "fraud_knowledge_hybrid_50_50"  # 0.5 embedding / 0.5 keyword
    KEYWORD_HEAVY = "fraud_knowledge_hybrid_20_80"  # 0.2 embedding / 0.8 keyword


@dataclass(frozen=True)
class FraudKnowledgeSearchResult:
    document: FraudKnowledgeDocument
    score: float


class FraudKnowledgeSearchPort(ABC):
    """Hybrid (embedding + keyword) search over the fraud knowledge base.

    `channel` is the mandatory exact-match filter on `segmento`. Query
    embedding happens inside the adapter, not the caller.
    """

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        channel: str,
        document_type: DocumentType,
        top_k: int = 5,
    ) -> list[FraudKnowledgeSearchResult]: ...
