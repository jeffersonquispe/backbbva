from __future__ import annotations

from src.application.errors import ConflictError
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeSearchPort,
    FraudKnowledgeSearchResult,
    SearchPipeline,
)
from src.application.ports.monitoring_port import MonitoringPort, ResearchCallOutcome
from src.application.ports.vector_store_generation_port import (
    VectorStoreGeneration,
    VectorStoreGenerationRepository,
    VectorStoreGenerationStatus,
)


class VectorStoreGenerationUnavailableError(ConflictError):
    """The requested generation does not exist, is not READY (still building,
    failed or retired), or the instance has no READY generation at all."""


def resolve_vector_store_generation(
    generations: VectorStoreGenerationRepository,
    vector_store_id: str,
    vector_store_generation: int | None,
) -> VectorStoreGeneration:
    if vector_store_generation is not None:
        generation = generations.get(vector_store_id, vector_store_generation)
        if generation is None or generation.status != VectorStoreGenerationStatus.READY:
            state = generation.status.value if generation else "missing"
            raise VectorStoreGenerationUnavailableError(
                f"vector store {vector_store_id} generation "
                f"{vector_store_generation} is not available ({state})"
            )
        return generation
    ready = [
        item
        for item in generations.list(vector_store_id)
        if item.status == VectorStoreGenerationStatus.READY
    ]
    if not ready:
        raise VectorStoreGenerationUnavailableError(
            f"vector store {vector_store_id} has no built generation"
        )
    return max(ready, key=lambda item: item.generation)


class SearchFraudKnowledgeUseCase:
    """Searches exactly one generation of one vector store - never across
    every generation loaded for this vector_store_id.

    Callers that run alerts pass the generation their configuration pins.
    Without one (Biblioteca's query panel, rows saved before generations
    existed) the latest READY generation is used."""

    def __init__(
        self,
        search_port: FraudKnowledgeSearchPort,
        generations: VectorStoreGenerationRepository,
        monitoring: MonitoringPort | None = None,
    ) -> None:
        self._search_port = search_port
        self._generations = generations
        self._monitoring = monitoring

    def execute(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        vector_store_id: str,
        document_type: DocumentType,
        top_k: int = 5,
        vector_store_generation: int | None = None,
    ) -> list[FraudKnowledgeSearchResult]:
        try:
            generation = resolve_vector_store_generation(
                self._generations, vector_store_id, vector_store_generation
            )
        except VectorStoreGenerationUnavailableError:
            if self._monitoring is not None:
                self._monitoring.record_research_call("vector_store", ResearchCallOutcome.FAILED)
            raise
        return self._search_port.search(
            query,
            pipeline=pipeline,
            vector_store_id=vector_store_id,
            vector_store_version=generation.generation,
            document_type=document_type,
            top_k=top_k,
        )
