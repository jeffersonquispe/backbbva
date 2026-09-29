"""Workflow adapters for bounded delegated research."""
from __future__ import annotations

from typing import Any

from src.application.dtos.research_dtos import HistoryOperation, ResearchRequest
from src.application.ports.fraud_knowledge_port import DocumentType, SearchPipeline
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)


class WorkflowVectorStoreRetriever:
    """Adapts promoted-store search to the delegated-research port."""

    _DOCUMENT_TYPES = {
        "taxonomy": DocumentType.TAXONOMIA,
        "modus_operandi": DocumentType.MODUS_OPERANDI,
        "similar_case": DocumentType.SIMILAR_CASE,
        # Both flag colours are useful to the investigator. Red is the
        # canonical query type; yellow flags remain available through direct
        # retrieval until the store supports multi-type queries.
        "flag": DocumentType.RED_FLAG,
    }

    def __init__(self, search: SearchFraudKnowledgeUseCase, vector_store_id: str) -> None:
        self._search = search
        self._vector_store_id = vector_store_id

    def search(
        self, query: str, *, asset_type: str, top_k: int
    ) -> list[dict[str, object]]:
        document_type = self._DOCUMENT_TYPES.get(asset_type)
        if document_type is None:
            return []
        hits = self._search.execute(
            query,
            pipeline=SearchPipeline.BALANCED,
            vector_store_id=self._vector_store_id,
            document_type=document_type,
            top_k=top_k,
        )
        return [
            {"id": str(hit.document.id), "text": hit.document.text, "score": hit.score}
            for hit in hits
        ]


class HeuristicHistoryResearchPlanner:
    """A restricted planner for the history analysis' first release.

    It deliberately emits declarative operations rather than arbitrary code.
    A future LLM planner can implement the same port without changing the
    executor or its data boundary.
    """

    def __init__(self, current_amount: Any = None) -> None:
        self._current_amount = current_amount

    def plan(self, request: ResearchRequest) -> list[HistoryOperation]:
        operations = [
            HistoryOperation("distribution", column="event_type"),
            HistoryOperation("group_by", group_by="channel"),
        ]
        if self._current_amount is not None:
            operations.extend([
                HistoryOperation(
                    "comparison", column="amount", current_value=self._current_amount
                ),
                HistoryOperation(
                    "outlier", column="amount", current_value=self._current_amount
                ),
            ])
        return operations
