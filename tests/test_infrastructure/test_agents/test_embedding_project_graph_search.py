from __future__ import annotations

import time

from src.application.ports.embedding_port import EmbeddingResult, EmbeddingUnitOfWork
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.project_graph_port import ProjectGraphRepository
from src.domain.project_graph.entities import GraphNode, NodeKind, ProjectGraph
from src.infrastructure.agents.embedding_project_graph_search import (
    BATCH_SIZE,
    EmbeddingProjectGraphSemanticSearch,
)


class InMemoryEmbeddings(EmbeddingUnitOfWork):
    """Two-dimensional 'meaning': [mentions models, mentions lists]."""

    def __init__(self, log: list[tuple[str, int]], operation: str) -> None:
        self._log = log
        self._operation = operation

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self._log.append((self._operation, len(texts)))
        vectors = [
            [float("model" in text.lower()), float("lista" in text.lower())]
            for text in texts
        ]
        return EmbeddingResult(vectors=vectors, model="fake", dimensions=2)


class RecordingEmbeddingFactory(EmbeddingUnitOfWorkFactory):
    def __init__(self) -> None:
        self.log: list[tuple[str, int]] = []

    def create(
        self, *, model: str, monitoring: MonitoringPort, operation_name: str
    ) -> EmbeddingUnitOfWork:
        return InMemoryEmbeddings(self.log, operation_name)


class StaticGraph(ProjectGraphRepository):
    def __init__(self, graph: ProjectGraph) -> None:
        self.graph = graph

    def load(self) -> ProjectGraph:
        return self.graph


def _graph(extra: int = 0) -> ProjectGraph:
    nodes = [
        GraphNode("view:/modelos", NodeKind.VIEW, "/modelos", "Modelos", (), "Modelos"),
        GraphNode(
            "view:/biblioteca",
            NodeKind.VIEW,
            "/biblioteca",
            "Una lista",
            (),
            "Biblioteca",
        ),
        GraphNode("endpoint:x", NodeKind.ENDPOINT, "GET /x", "modelo"),  # not embedded
    ]
    nodes += [
        GraphNode(f"component:c{i}", NodeKind.COMPONENT, f"C{i}", "otra cosa")
        for i in range(extra)
    ]
    return ProjectGraph(nodes={node.node_id: node for node in nodes})


def _search(
    graph: ProjectGraph,
) -> tuple[EmbeddingProjectGraphSemanticSearch, RecordingEmbeddingFactory]:
    factory = RecordingEmbeddingFactory()
    return (
        EmbeddingProjectGraphSemanticSearch(
            graph=StaticGraph(graph),
            embeddings=factory,
            monitoring=None,  # type: ignore[arg-type]
            model="fake",
        ),
        factory,
    )


def test_ranks_by_cosine_and_skips_backend_only_kinds() -> None:
    search, _ = _search(_graph())
    search.warm()

    assert search.rank("entrenar un modelo", 5)[0] == "view:/modelos"
    assert search.rank("crear una lista", 5)[0] == "view:/biblioteca"
    assert "endpoint:x" not in search.rank("modelo", 10)


def test_index_is_built_once_in_batches() -> None:
    search, factory = _search(_graph(extra=BATCH_SIZE + 5))
    search.warm()

    search.rank("modelo", 3)
    search.rank("lista", 3)

    indexing = [size for op, size in factory.log if op == "project_graph_index"]
    assert sorted(indexing) == [
        7,
        BATCH_SIZE,
    ]  # 2 views + BATCH_SIZE + 5 components = 71
    assert [op for op, _ in factory.log].count("project_graph_query") == 2


def test_empty_graph_ranks_nothing() -> None:
    search, _ = _search(ProjectGraph())
    search.warm()

    assert search.rank("modelo", 5) == []


def test_first_rank_never_blocks_on_indexing_and_the_index_arrives_later() -> None:
    search, _ = _search(_graph())

    assert search.rank("modelo", 3) == []  # started in the background, no wait
    for _ in range(100):
        ranked = search.rank("modelo", 3)
        if ranked:
            break
        time.sleep(0.02)
    assert ranked[0] == "view:/modelos"


class FailingEmbeddingFactory(RecordingEmbeddingFactory):
    def create(self, *, model, monitoring, operation_name):
        raise RuntimeError("embedding service down")


def test_a_failed_build_returns_nothing_and_does_not_raise() -> None:
    search = EmbeddingProjectGraphSemanticSearch(
        graph=StaticGraph(_graph()),
        embeddings=FailingEmbeddingFactory(),
        monitoring=None,  # type: ignore[arg-type]
        model="fake",
    )

    assert search.rank("modelo", 3) == []
    time.sleep(0.1)
    assert search.rank("modelo", 3) == []  # retry is throttled, still no error
