from __future__ import annotations

from src.application.ports.fraud_knowledge_port import DocumentType, SearchPipeline
from src.application.ports.fraud_similarity_port import (
    SimilarFraudCase,
    SimilarFraudCasePort,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
    VectorStoreNotPromotedError,
)


class OpenSearchSimilarFraudCaseAdapter(SimilarFraudCasePort):
    """Real SimilarFraudCasePort adapter, backed by SearchFraudKnowledgeUseCase.

    See OpenSearchFraudTaxonomyAdapter's docstring for why this is bound to
    one vector_store_instance_id at construction time rather than per call.
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

    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudCase]:
        try:
            results = self._search_use_case.execute(
                query,
                pipeline=self._pipeline,
                vector_store_id=self._vector_store_instance_id,
                document_type=DocumentType.SIMILAR_CASE,
                top_k=top_k,
            )
        except VectorStoreNotPromotedError:
            return []
        return [
            SimilarFraudCase(
                # See OpenSearchFraudTaxonomyAdapter's comment - the
                # OpenSearch document's own id, not a Library entry id.
                case_id=str(result.document.id),
                summary=result.document.text,
                # SimilarCaseDocument/SimilarCaseLibraryEntry never capture
                # an "outcome" field anywhere in the domain today - this
                # port dataclass was shaped against the old Mock's made-up
                # field, not a real source. Left blank rather than guessed;
                # revisit if the product wants to capture case outcomes.
                outcome="",
                similarity_score=result.score,
            )
            for result in results
        ]
