"""Workflow adapters for bounded delegated research."""

from __future__ import annotations

import json
from typing import Any

from src.application.dtos.research_dtos import HistoryOperation, ResearchRequest
from src.application.ports.fraud_knowledge_port import DocumentType, SearchPipeline
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import LLMMessage, LLMMessageRole
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)


class WorkflowVectorStoreRetriever:
    """Adapts pinned-generation search to the delegated-research port."""

    _DOCUMENT_TYPES = {
        "taxonomy": DocumentType.TAXONOMIA,
        "modus_operandi": DocumentType.MODUS_OPERANDI,
        "similar_case": DocumentType.SIMILAR_CASE,
        # Both flag colours are useful to the investigator. Red is the
        # canonical query type; yellow flags remain available through direct
        # retrieval until the store supports multi-type queries.
        "flag": DocumentType.RED_FLAG,
    }

    def __init__(
        self,
        search: SearchFraudKnowledgeUseCase,
        vector_store_id: str,
        vector_store_generation: int | None = None,
    ) -> None:
        self._search = search
        self._vector_store_id = vector_store_id
        self._vector_store_generation = vector_store_generation

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
            vector_store_generation=self._vector_store_generation,
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

    kind = "heuristic"

    def __init__(self, current_amount: Any = None) -> None:
        self._current_amount = current_amount

    def plan(self, request: ResearchRequest) -> list[HistoryOperation]:
        operations = [
            HistoryOperation("distribution", column="event_type"),
            HistoryOperation("group_by", group_by="channel"),
        ]
        if self._current_amount is not None:
            operations.extend(
                [
                    HistoryOperation(
                        "comparison",
                        column="amount",
                        current_value=self._current_amount,
                    ),
                    HistoryOperation(
                        "outlier", column="amount", current_value=self._current_amount
                    ),
                ]
            )
        return operations


class LLMHistoryResearchPlanner:
    """Plans bounded history operations from the alert question and schema.

    The model only returns JSON in the executor's closed operation language;
    it never receives transaction rows or executable code.
    """

    _SYSTEM = (
        "Eres un planificador de análisis de historial transaccional. Devuelve "
        "solo JSON con la forma {\"operations\":[{\"name\":..., ...}]}. "
        "Usa exclusivamente columnas y operaciones permitidas. Operaciones: "
        "filter (column, operator eq/ne/gt/gte/lt/lte/in, value), aggregate "
        "(column, aggregate count/sum/mean/median/min/max/nunique), distribution "
        "(column), group_by (group_by, opcional column y aggregate), comparison "
        "(column, current_value), outlier (column, current_value), trend "
        "(column de fecha, group_by frecuencia). No infieras hechos; si no hay "
        "columnas útiles, devuelve operations vacío. Máximo 4 operaciones."
    )

    kind = "llm"

    def __init__(
        self,
        llm_factory: LLMUnitOfWorkFactory,
        *,
        model: str,
        monitoring: MonitoringPort,
        columns: list[str],
        allowed_operations: list[str],
        max_operations: int,
    ) -> None:
        self._llm_factory = llm_factory
        self._model = model
        self._monitoring = monitoring
        self._columns = columns
        self._allowed_operations = set(allowed_operations)
        self._max_operations = min(max_operations, 4)
        # Token usage of the latest plan, for the planner comparison trace.
        self.usage: dict[str, int | None] = {}

    def plan(self, request: ResearchRequest) -> list[HistoryOperation]:
        payload = {
            "question": request.question,
            "alert_context": request.alert_context,
            "available_columns": self._columns,
            "allowed_operations": sorted(self._allowed_operations),
        }
        response = self._llm_factory.create(
            model=self._model,
            monitoring=self._monitoring,
            operation_name="plan_history_research",
            temperature=0.0,
            max_tokens=600,
        ).invoke(
            [
                LLMMessage(
                    LLMMessageRole.SYSTEM,
                    self._SYSTEM
                    + f" Límite configurado: {self._max_operations} operaciones.",
                ),
                LLMMessage(LLMMessageRole.USER, json.dumps(payload, ensure_ascii=False)),
            ]
        )
        self.usage = {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        }
        parsed = json.loads(response.content)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("operations"), list):
            raise ValueError("invalid history plan response")
        operations: list[HistoryOperation] = []
        for raw in parsed["operations"][: self._max_operations]:
            if not isinstance(raw, dict) or raw.get("name") not in self._allowed_operations:
                continue
            operation = HistoryOperation(**{
                key: raw[key]
                for key in HistoryOperation.__dataclass_fields__
                if key in raw
            })
            columns = (operation.column, operation.group_by)
            if any(column and column not in self._columns for column in columns):
                continue
            operations.append(operation)
        return operations
