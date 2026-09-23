from __future__ import annotations

from src.application.ports.fraud_knowledge_port import DocumentType, SearchPipeline
from src.application.ports.fraud_taxonomy_port import (
    FraudTaxonomyPort,
    SimilarFraudTaxonomy,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
    VectorStoreNotPromotedError,
)


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
    ) -> None:
        self._search_use_case = search_use_case
        self._vector_store_instance_id = vector_store_instance_id
        self._pipeline = pipeline

    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudTaxonomy]:
        try:
            results = self._search_use_case.execute(
                query,
                pipeline=self._pipeline,
                vector_store_id=self._vector_store_instance_id,
                document_type=DocumentType.TAXONOMIA,
                top_k=top_k,
            )
        except VectorStoreNotPromotedError:
            # The segment's config points at a vector store that was never
            # promoted (or was un-promoted) - fail open with no results
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
