from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.project_graph_port import ProjectGraphRepository
from src.application.ports.project_graph_semantic_port import (
    ProjectGraphSemanticSearch,
)
from src.domain.project_graph.entities import GraphNode, NodeKind

# What a user can ask about; backend layers are reached through graph spreading.
EMBEDDED_KINDS = frozenset(
    {
        NodeKind.VIEW,
        NodeKind.TASK,
        NodeKind.CONCEPT,
        NodeKind.COMPONENT,
        NodeKind.ACTION,
    }
)
BATCH_SIZE = 64
PARALLEL_BATCHES = 4
RETRY_SECONDS = 60.0


class EmbeddingProjectGraphSemanticSearch(ProjectGraphSemanticSearch):
    """Cosine search over node embeddings.

    Indexing ~400 nodes takes tens of seconds, so it never runs inside a chat
    request: the first ``rank`` starts it on a background thread and returns
    ``[]`` (the caller falls back to BM25) until the vectors are ready. A failed
    build is retried after ``RETRY_SECONDS``.
    """

    def __init__(
        self,
        *,
        graph: ProjectGraphRepository,
        embeddings: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
    ) -> None:
        self._graph = graph
        self._embeddings = embeddings
        self._monitoring = monitoring
        self._model = model
        self._lock = threading.Lock()
        self._vectors: dict[str, list[float]] | None = None
        self._building = False
        self._retry_at = 0.0

    def rank(self, query: str, limit: int) -> list[str]:
        vectors = self._vectors
        if vectors is None:
            self._start_warmup()
            return []
        if not vectors:
            return []
        query_vector = self._unit("project_graph_query").embed([query]).vectors[0]
        scored = sorted(
            (
                (_cosine(query_vector, vector), node_id)
                for node_id, vector in vectors.items()
            ),
            reverse=True,
        )
        return [node_id for _score, node_id in scored[:limit]]

    def warm(self) -> None:
        """Build the index now, on the calling thread (tests, startup hooks)."""
        self._vectors = self._build()

    def _start_warmup(self) -> None:
        with self._lock:
            if self._building or time.monotonic() < self._retry_at:
                return
            self._building = True
        threading.Thread(target=self._warm_in_background, daemon=True).start()

    def _warm_in_background(self) -> None:
        try:
            self._vectors = self._build()
        except Exception:  # noqa: BLE001 - BM25 keeps answering; retry later
            self._retry_at = time.monotonic() + RETRY_SECONDS
        finally:
            self._building = False

    def _unit(self, operation: str):
        return self._embeddings.create(
            model=self._model, monitoring=self._monitoring, operation_name=operation
        )

    def _build(self) -> dict[str, list[float]]:
        nodes = [
            node
            for node in self._graph.load().nodes.values()
            if node.kind in EMBEDDED_KINDS
        ]
        batches = [nodes[i : i + BATCH_SIZE] for i in range(0, len(nodes), BATCH_SIZE)]

        def embed(batch: list[GraphNode]) -> list[list[float]]:
            return (
                self._unit("project_graph_index")
                .embed([_text(node) for node in batch])
                .vectors
            )

        vectors: dict[str, list[float]] = {}
        with ThreadPoolExecutor(max_workers=PARALLEL_BATCHES) as pool:
            for batch, result in zip(batches, pool.map(embed, batches), strict=True):
                vectors.update(
                    {node.node_id: vec for node, vec in zip(batch, result, strict=True)}
                )
        return vectors


def _text(node: GraphNode) -> str:
    parts = [node.display, node.description, "; ".join(node.keywords[:12])]
    return ". ".join(part for part in parts if part)[:1_000]


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0
