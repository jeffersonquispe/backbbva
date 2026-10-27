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


# Every document lives in one shared OpenSearch index, scoped by
# `vector_store_id` (the VectorStoreInstance.id it belongs to, see
# vector_store_instance_port.py) rather than by channel/segmento - a vector
# store is channel-agnostic by design, several segments' agent configs can
# point at the same one. `vector_store_version` is the immutable generation
# (vector_store_generation_port.py) the document was loaded into: many
# generations of one vector store coexist in the index, and every search
# filters on the one its configuration pins.


@dataclass(frozen=True)
class TaxonomiaDocument:
    id: UUID
    text: str
    text_embedded: list[float]
    vector_store_id: str
    vector_store_version: int
    type: DocumentType = DocumentType.TAXONOMIA


@dataclass(frozen=True)
class ModusOperandiDocument:
    id: UUID
    text: str
    text_embedded: list[float]
    vector_store_id: str
    vector_store_version: int
    taxonomia_id: UUID
    taxonomia: str
    similar_cases: list[UUID]
    flags: list[UUID]
    # The source ModusOperandiLibraryEntry.id this document was promoted
    # from - `id` above is this document's own fresh uuid4 (see
    # ingest_modus_operandi.py), which changes every re-promotion, so it
    # can't be used to join a search hit back to a stable, admin-referenced
    # Library entry (e.g. to read its playbook - see
    # resolve_analyst_playbook.py). Defaults to "" (not populated) rather
    # than raising, so documents indexed before this field existed still
    # deserialize during a promotion's own delete-previous-generation pass.
    library_id: str = ""
    type: DocumentType = DocumentType.MODUS_OPERANDI


@dataclass(frozen=True)
class SimilarCaseDocument:
    id: UUID
    text: str
    text_embedded: list[float]
    vector_store_id: str
    vector_store_version: int
    modus_operandi_id: UUID
    taxonomia_id: UUID
    type: DocumentType = DocumentType.SIMILAR_CASE


@dataclass(frozen=True)
class FlagDocument:
    # Many-to-many with ModusOperandiDocument (see `modus_operandi_ids`) -
    # no `taxonomia_id`, since a flag's taxonomy is derived from whichever
    # modus operandi it's attached to, not a single denormalized value.
    # `type` still discriminates red vs. yellow (DocumentType.RED_FLAG /
    # .YELLOW_FLAG) - the two colors share this one document shape.
    id: UUID
    text: str
    text_embedded: list[float]
    vector_store_id: str
    vector_store_version: int
    modus_operandi_ids: list[UUID]
    type: DocumentType = DocumentType.RED_FLAG


FraudKnowledgeDocument = (
    TaxonomiaDocument | ModusOperandiDocument | SimilarCaseDocument | FlagDocument
)


class SearchPipeline(StrEnum):
    """Search relevance profile; adapters map it to backend-specific ids."""

    EMBEDDING_HEAVY = "embedding_heavy"
    BALANCED = "balanced"
    KEYWORD_HEAVY = "keyword_heavy"


@dataclass(frozen=True)
class FraudKnowledgeSearchResult:
    document: FraudKnowledgeDocument
    score: float


class FraudKnowledgeSearchPort(ABC):
    """Hybrid (embedding + keyword) search over the fraud knowledge base.

    `vector_store_id` + `vector_store_version` are the mandatory exact-match
    filter - every search is scoped to exactly one generation of one vector
    store, never the whole shared index. Resolving which generation is the
    caller's job (see
    SearchFraudKnowledgeUseCase) - this port just filters on the values it's
    given. Query embedding happens inside the adapter, not the caller.
    """

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        vector_store_id: str,
        vector_store_version: int,
        document_type: DocumentType,
        top_k: int = 5,
    ) -> list[FraudKnowledgeSearchResult]: ...
