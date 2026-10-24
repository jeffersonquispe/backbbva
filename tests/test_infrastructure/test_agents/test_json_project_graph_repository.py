from __future__ import annotations

import json
from pathlib import Path

from src.application.use_cases.agent.retrieve_project_context import (
    RetrieveProjectContextInput,
    RetrieveProjectContextUseCase,
)
from src.domain.project_graph.entities import NodeKind
from src.infrastructure.agents.json_project_graph_repository import (
    DEFAULT_GRAPH_PATH,
    JsonProjectGraphRepository,
)


def test_missing_file_yields_an_empty_graph(tmp_path: Path) -> None:
    graph = JsonProjectGraphRepository(tmp_path / "nope.json").load()

    assert graph.nodes == {}
    assert graph.edges == ()


def test_unknown_kinds_are_skipped_and_edges_are_loaded(tmp_path: Path) -> None:
    path = tmp_path / "graph.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "view:/a", "kind": "view", "name": "/a"},
                    {"id": "x:1", "kind": "martian", "name": "x"},
                ],
                "edges": [
                    {"source": "view:/a", "target": "x:1", "relation": "renders"}
                ],
            }
        ),
        encoding="utf-8",
    )

    graph = JsonProjectGraphRepository(path).load()

    assert list(graph.nodes) == ["view:/a"]
    assert graph.nodes["view:/a"].kind is NodeKind.VIEW
    assert len(graph.edges) == 1


def test_committed_graph_covers_every_node_kind_and_has_no_dangling_edges() -> None:
    graph = JsonProjectGraphRepository(DEFAULT_GRAPH_PATH).load()

    assert {node.kind for node in graph.nodes.values()} == set(NodeKind)
    assert all(
        edge.source in graph.nodes and edge.target in graph.nodes
        for edge in graph.edges
    )


def test_committed_graph_answers_real_questions_with_the_right_view() -> None:
    use_case = RetrieveProjectContextUseCase(
        graph=JsonProjectGraphRepository(DEFAULT_GRAPH_PATH)
    )

    def ids(query: str, page: str = "") -> tuple[str, ...]:
        return use_case.execute(
            RetrieveProjectContextInput(query=query, page_path=page)
        ).node_ids

    assert "view:/historico-fraude" in ids("revisar fraude en el histórico de gestión")
    assert "view:/modelos" in ids("entrenar y activar un modelo")
    # On any page the current view is part of the context, whatever was asked.
    assert "view:/testing" in ids("qué puedo hacer aquí", "/testing/abc123")
