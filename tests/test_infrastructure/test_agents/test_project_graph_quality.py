"""Quality gate for the committed project graph and its retrieval.

* structure: no dangling edges, every task/concept/view is wired and described;
* recall: every golden question retrieves one of its expected nodes;
* safety: whatever the role, retrieval never surfaces a node hidden for it.

Add a golden question whenever a real user question is answered badly, then fix
the graph (curated aliases / descriptions) or the retrieval until it passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.application.use_cases.agent.retrieve_project_context import (
    RetrieveProjectContextInput,
    RetrieveProjectContextUseCase,
)
from src.domain.project_graph.entities import NodeKind
from src.infrastructure.agents.json_project_graph_repository import (
    DEFAULT_GRAPH_PATH,
    JsonProjectGraphRepository,
)

GOLDEN = json.loads(
    (Path(__file__).parent / "project_graph_golden.json").read_text(encoding="utf-8")
)
ROLES = (
    "manager",
    "release_manager",
    "channel_manager",
    "data_analyst",
    "fraud_analyst",
    "ops_analyst",
    "fraud_reviewer",
)


@pytest.fixture(scope="module")
def repository() -> JsonProjectGraphRepository:
    return JsonProjectGraphRepository(DEFAULT_GRAPH_PATH)


@pytest.fixture(scope="module")
def use_case(repository: JsonProjectGraphRepository) -> RetrieveProjectContextUseCase:
    return RetrieveProjectContextUseCase(graph=repository)


def test_graph_has_no_dangling_edges_and_every_kind(
    repository: JsonProjectGraphRepository,
) -> None:
    graph = repository.load()

    assert {node.kind for node in graph.nodes.values()} == set(NodeKind)
    dangling = [
        edge
        for edge in graph.edges
        if edge.source not in graph.nodes or edge.target not in graph.nodes
    ]
    assert dangling == []


def test_tasks_concepts_and_views_are_wired_and_described(
    repository: JsonProjectGraphRepository,
) -> None:
    graph = repository.load()
    problems: list[str] = []
    for node_id, node in graph.nodes.items():
        if node.kind is NodeKind.TASK:
            if not graph.outgoing(node_id, "starts_at"):
                problems.append(f"{node_id}: no starts_at")
            if not graph.outgoing(node_id, "involves"):
                problems.append(f"{node_id}: no steps")
        if node.kind is NodeKind.CONCEPT and not graph.outgoing(
            node_id, "manifested_in"
        ):
            problems.append(f"{node_id}: not manifested anywhere")
        if node.kind in {NodeKind.VIEW, NodeKind.TASK, NodeKind.CONCEPT}:
            if not node.description:
                problems.append(f"{node_id}: no description")
    assert problems == []


def test_components_have_curated_or_llm_generated_descriptions(
    repository: JsonProjectGraphRepository,
) -> None:
    graph = repository.load()

    missing = [
        node.node_id
        for node in graph.nodes.values()
        if node.kind is NodeKind.COMPONENT and not node.description.strip()
    ]

    assert missing == []


def test_every_golden_question_retrieves_an_expected_node(
    use_case: RetrieveProjectContextUseCase,
) -> None:
    misses = []
    for case in GOLDEN:
        result = use_case.execute(
            RetrieveProjectContextInput(
                query=case["query"], page_path=case["page"], role=case["role"]
            )
        )
        if not set(case["expect"]) & set(result.node_ids):
            misses.append((case["query"], case["expect"], result.node_ids[:6]))
    assert misses == []


def test_retrieval_never_surfaces_nodes_hidden_for_the_role(
    repository: JsonProjectGraphRepository, use_case: RetrieveProjectContextUseCase
) -> None:
    graph = repository.load()
    leaks = []
    for role in ROLES:
        hidden = graph.hidden_for(role)
        for case in GOLDEN:
            result = use_case.execute(
                RetrieveProjectContextInput(
                    query=case["query"], page_path=case["page"], role=role
                )
            )
            leaked = hidden & set(result.node_ids)
            if leaked:
                leaks.append((role, case["query"], sorted(leaked)))
    assert leaks == []


def test_role_gating_matches_the_navigation_of_each_role(
    repository: JsonProjectGraphRepository,
) -> None:
    graph = repository.load()

    assert "view:/modelos" in graph.hidden_for("fraud_analyst")
    assert "view:/modelos" not in graph.hidden_for("data_analyst")
    assert "view:/cola" in graph.hidden_for("data_analyst")
    # Backend gating: endpoints behind a permission the role was not granted.
    assert "endpoint:POST /api/v0/models/{model_id}/train" in graph.hidden_for(
        "fraud_analyst"
    )
