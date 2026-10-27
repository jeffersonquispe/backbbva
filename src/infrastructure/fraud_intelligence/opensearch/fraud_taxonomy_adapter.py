from __future__ import annotations

import logging

from src.application.ports.fraud_knowledge_port import DocumentType, SearchPipeline
from src.application.ports.fraud_taxonomy_port import (
    FraudTaxonomyPort,
    SimilarFraudTaxonomy,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
    VectorStoreGenerationUnavailableError,
)

logger = logging.getLogger(__name__)


class OpenSearchFraudTaxonomyAdapter(FraudTaxonomyPort):
    """Real FraudTaxonomyPort adapter, backed by SearchFraudKnowledgeUseCase.

    Bound to one already-resolved `vector_store_instance_id` at construction
    time - find_similar's signature (query, top_k) is fixed by the port and
    is what the LLM calls directly as a ReAct tool, so there's no room to
    pass the vector store per call (see factories.py's get_fraud_taxonomy_port).
    """

    def __init__(
        self,
        search_use_case: SearchFraudKnowledgeUseCase,
        vector_store_instance_id: str,
        pipeline: SearchPipeline = SearchPipeline.BALANCED,
        vector_store_generation: int | None = None,
    ) -> None:
        self._search_use_case = search_use_case
        self._vector_store_instance_id = vector_store_instance_id
        self._pipeline = pipeline
        self._vector_store_generation = vector_store_generation

    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudTaxonomy]:
        try:
            results = self._search_use_case.execute(
                query,
                pipeline=self._pipeline,
                vector_store_id=self._vector_store_instance_id,
                vector_store_generation=self._vector_store_generation,
                document_type=DocumentType.TAXONOMIA,
                top_k=top_k,
            )
        except VectorStoreGenerationUnavailableError as error:
            logger.warning("Vector store search skipped: %s", error)
            # The segment's pinned generation is not READY (retired, or the
            # row predates generations and nothing was built) - fail open
            # rather than crashing the whole classification/detector step
            # over a knowledge-base configuration issue.
            return []
        return [
            SimilarFraudTaxonomy(
                # TaxonomiaDocument only stores the denormalized embedding
                # text ("{name}: {description}", see
                # taxonomy_library/create_taxonomy_library_entry.py's
                # embedding_text) - the source TaxonomyLibraryEntry.code
                # isn't carried onto the document, so the OpenSearch
                # document's own id is the closest stable identifier
                # available here.
                code=str(result.document.id),
                name=result.document.text,
                description=result.document.text,
                similarity_score=result.score,
            )
            for result in results
        ]
