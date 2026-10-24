from __future__ import annotations

from src.application.ports.project_graph_port import ProjectGraphRepository
from src.application.ports.project_graph_semantic_port import (
    ProjectGraphSemanticSearch,
)
from src.application.use_cases.agent.retrieve_project_context import (
    RetrieveProjectContextInput,
    RetrieveProjectContextUseCase,
    tokenize,
)
from src.domain.project_graph.entities import (
    GraphEdge,
    GraphNode,
    NodeKind,
    ProjectGraph,
)


class InMemoryProjectGraph(ProjectGraphRepository):
    """view -> component -> action/api_call -> endpoint -> use_case, plus noise."""

    def __init__(self, graph: ProjectGraph | None = None) -> None:
        self.graph = graph if graph is not None else _sample_graph()

    def load(self) -> ProjectGraph:
        return self.graph


def _sample_graph() -> ProjectGraph:
    nodes = [
        GraphNode(
            "view:/biblioteca", NodeKind.VIEW, "/biblioteca", "Vista «Biblioteca»."
        ),
        GraphNode("view:/modelos", NodeKind.VIEW, "/modelos", "Vista «Modelos»."),
        GraphNode(
            "component:WatchlistManager",
            NodeKind.COMPONENT,
            "WatchlistManager",
            "Gestiona listas de vigilancia.",
            ("Nueva watchlist", "Importar elementos"),
        ),
        GraphNode(
            "action:importar",
            NodeKind.ACTION,
            "Importar CSV",
            "Acción en WatchlistManager.",
            ("Importar CSV",),
        ),
        GraphNode(
            "api:createWatchlist",
            NodeKind.API_CALL,
            "createWatchlist",
            "Crea una watchlist.",
        ),
        GraphNode(
            "endpoint:POST /api/v0/watchlists",
            NodeKind.ENDPOINT,
            "POST /api/v0/watchlists",
            "Endpoint create watchlist.",
        ),
        GraphNode(
            "use_case:CreateWatchlistUseCase",
            NodeKind.USE_CASE,
            "CreateWatchlistUseCase",
            "Caso de uso Create Watchlist.",
        ),
        GraphNode(
            "component:ModelTable",
            NodeKind.COMPONENT,
            "ModelTable",
            "Tabla de modelos entrenados.",
            ("Entrenar", "Activar"),
        ),
    ]
    edges = (
        GraphEdge("view:/biblioteca", "component:WatchlistManager", "renders"),
        GraphEdge("component:WatchlistManager", "action:importar", "offers"),
        GraphEdge("component:WatchlistManager", "api:createWatchlist", "calls"),
        GraphEdge(
            "api:createWatchlist", "endpoint:POST /api/v0/watchlists", "requests"
        ),
        GraphEdge(
            "endpoint:POST /api/v0/watchlists",
            "use_case:CreateWatchlistUseCase",
            "handled_by",
        ),
        GraphEdge("view:/modelos", "component:ModelTable", "renders"),
    )
    return ProjectGraph(nodes={n.node_id: n for n in nodes}, edges=edges)


def _retrieve(query: str, page_path: str = "", **kwargs) -> tuple[str, tuple[str, ...]]:
    result = RetrieveProjectContextUseCase(graph=InMemoryProjectGraph()).execute(
        RetrieveProjectContextInput(query=query, page_path=page_path, **kwargs)
    )
    return result.text, result.node_ids


def test_tokenize_folds_accents_drops_stopwords_and_stems_lightly() -> None:
    assert tokenize("¿Cómo creo las Watchlists en la página?") == [
        "cre",
        "watchlist",
        "pagin",
    ]
    # Conjugations meet: "subo", "subir" and "subiendo" share a stem.
    assert tokenize("subo") == tokenize("subir") == tokenize("subiendo")


def test_query_seeds_a_component_and_spreads_to_its_backend_chain() -> None:
    text, ids = _retrieve("crear una watchlist")

    assert "component:WatchlistManager" in ids
    # Two hops from the component reach endpoint and use case.
    assert "endpoint:POST /api/v0/watchlists" in ids
    assert "use_case:CreateWatchlistUseCase" in ids
    assert "WatchlistManager -calls-> createWatchlist" in text
    assert "ModelTable" not in text


def test_current_page_is_always_a_seed_even_without_lexical_match() -> None:
    text, ids = _retrieve("zzz qqq", page_path="/modelos/detalle")

    assert ids[0] == "view:/modelos" or "view:/modelos" in ids
    assert "component:ModelTable" in ids
    assert "Vistas:" in text


def test_page_path_is_only_a_lookup_key_and_never_echoed() -> None:
    text, ids = _retrieve("", page_path="/no-existe<script>")

    assert ids == ()
    assert text == ""


def test_empty_graph_or_no_match_returns_empty_context() -> None:
    empty = RetrieveProjectContextUseCase(graph=InMemoryProjectGraph(ProjectGraph()))
    assert empty.execute(RetrieveProjectContextInput(query="watchlist")).text == ""
    assert _retrieve("zzz qqq")[0] == ""


def test_output_respects_node_and_character_budgets() -> None:
    text, ids = _retrieve("watchlist", max_nodes=2, max_chars=80)

    assert len(ids) <= 2
    assert len(text) <= 80


# --- roles, tasks, history, semantic fusion --------------------------------


def _role_graph() -> ProjectGraph:
    nodes = [
        GraphNode(
            "view:/modelos",
            NodeKind.VIEW,
            "/modelos",
            "Modelos de fraude.",
            (),
            "Modelos",
        ),
        GraphNode(
            "view:/cola", NodeKind.VIEW, "/cola", "Cola de trabajo.", (), "En proceso"
        ),
        GraphNode(
            "view:/alerta/$id", NodeKind.VIEW, "/alerta/$id", "Detalle.", (), "Detalle"
        ),
        GraphNode(
            "task:entrenar",
            NodeKind.TASK,
            "Entrenar un modelo",
            "Pulsa Nuevo modelo y sigue el asistente.",
            ("crear modelo",),
        ),
        GraphNode(
            "action:nuevo@modelos",
            NodeKind.ACTION,
            "Nuevo modelo",
            "",
            ("Nuevo modelo",),
        ),
        GraphNode(
            "api:train",
            NodeKind.API_CALL,
            "trainModel",
            "POST /api/v0/models/{id}/train",
        ),
        GraphNode(
            "endpoint:train",
            NodeKind.ENDPOINT,
            "POST /api/v0/models/{model_id}/train",
            "",
        ),
        GraphNode("permission:models", NodeKind.PERMISSION, "models"),
        GraphNode("role:data_analyst", NodeKind.ROLE, "data_analyst"),
        GraphNode("role:fraud_analyst", NodeKind.ROLE, "fraud_analyst"),
    ]
    edges = (
        GraphEdge("role:data_analyst", "view:/modelos", "can_open"),
        GraphEdge("role:fraud_analyst", "view:/cola", "can_open"),
        GraphEdge("role:data_analyst", "permission:models", "grants"),
        GraphEdge("task:entrenar", "view:/modelos", "starts_at"),
        GraphEdge("task:entrenar", "action:nuevo@modelos", "involves", 0),
        GraphEdge("task:entrenar", "api:train", "involves", 1),
        GraphEdge("view:/modelos", "action:nuevo@modelos", "offers"),
        GraphEdge("view:/modelos", "api:train", "calls"),
        GraphEdge("api:train", "endpoint:train", "requests"),
        GraphEdge("endpoint:train", "permission:models", "requires"),
        GraphEdge("view:/cola", "view:/alerta/$id", "navigates_to"),
    )
    return ProjectGraph(nodes={n.node_id: n for n in nodes}, edges=edges)


def _use_case(graph: ProjectGraph | None = None, semantic=None):
    return RetrieveProjectContextUseCase(
        graph=InMemoryProjectGraph(graph or _role_graph()), semantic=semantic
    )


def test_role_hides_views_tasks_actions_and_backend_behind_them() -> None:
    graph = _role_graph()

    hidden = graph.hidden_for("fraud_analyst")

    assert {"view:/modelos", "task:entrenar", "action:nuevo@modelos"} <= hidden
    assert {"api:train", "endpoint:train"} <= hidden
    assert "view:/cola" not in hidden
    assert graph.hidden_for("data_analyst") == frozenset({"view:/cola"}) | {
        "view:/alerta/$id"
    }
    # Unknown or empty role: nothing is hidden (the API still enforces access).
    assert graph.hidden_for("") == frozenset()
    assert graph.hidden_for("martian") == frozenset()


def test_retrieval_never_returns_what_the_role_cannot_reach() -> None:
    allowed = _use_case().execute(
        RetrieveProjectContextInput("entrenar un modelo", role="data_analyst")
    )
    blocked = _use_case().execute(
        RetrieveProjectContextInput("entrenar un modelo", role="fraud_analyst")
    )

    assert "task:entrenar" in allowed.node_ids
    assert "task:entrenar" not in blocked.node_ids
    assert "Entrenar un modelo" not in blocked.text
    assert "Rol del usuario: fraud_analyst" in blocked.text
    assert "su rol no tiene acceso" in blocked.text
    assert "su rol no tiene acceso" not in allowed.text


def test_task_steps_are_rendered_in_order_with_ids_for_citation() -> None:
    result = _use_case().execute(
        RetrieveProjectContextInput("cómo entrenar un modelo", role="data_analyst")
    )

    assert "[task:entrenar] Entrenar un modelo" in result.text
    assert "pasos: Nuevo modelo → trainModel" in result.text


def test_references_are_navigable_views_and_tasks_without_current_page() -> None:
    result = _use_case().execute(
        RetrieveProjectContextInput(
            "entrenar un modelo", page_path="/cola", role="data_analyst"
        )
    )

    paths = {ref.node_id: ref.path for ref in result.references}
    assert paths["task:entrenar"] == "/modelos"
    assert all("$" not in ref.path for ref in result.references)
    assert [ref.node_id for ref in result.suggested][0] == "task:entrenar"

    on_page = _use_case().execute(
        RetrieveProjectContextInput(
            "entrenar un modelo", page_path="/modelos", role="data_analyst"
        )
    )
    assert on_page.references == ()  # already there: nothing to navigate to


def test_history_adds_weak_terms_so_a_follow_up_still_finds_the_topic() -> None:
    use_case = _use_case()

    alone = use_case.execute(RetrieveProjectContextInput("¿y dónde está eso?"))
    followed = use_case.execute(
        RetrieveProjectContextInput(
            "¿y dónde está eso?", history=("quiero entrenar un modelo",)
        )
    )

    assert "task:entrenar" not in alone.node_ids
    assert "task:entrenar" in followed.node_ids


class RecordingSemanticSearch(ProjectGraphSemanticSearch):
    def __init__(self, ranked: list[str] | None = None, fail: bool = False) -> None:
        self.ranked = ranked or []
        self.fail = fail
        self.queries: list[str] = []

    def rank(self, query: str, limit: int) -> list[str]:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("embedding service down")
        return self.ranked[:limit]


def test_semantic_ranking_is_fused_with_bm25_and_respects_the_role() -> None:
    semantic = RecordingSemanticSearch(["view:/modelos", "task:entrenar", "view:/cola"])
    result = _use_case(semantic=semantic).execute(
        RetrieveProjectContextInput("zzz sin coincidencia lexica", role="fraud_analyst")
    )

    assert semantic.queries == ["zzz sin coincidencia lexica"]
    assert "view:/cola" in result.node_ids  # semantic-only hit, visible to the role
    assert "view:/modelos" not in result.node_ids  # hidden for that role


def test_semantic_failure_falls_back_to_bm25() -> None:
    result = _use_case(semantic=RecordingSemanticSearch(fail=True)).execute(
        RetrieveProjectContextInput("entrenar un modelo", role="data_analyst")
    )

    assert "task:entrenar" in result.node_ids


def test_describe_and_reference_for_respect_visibility() -> None:
    use_case = _use_case()

    text = use_case.describe("task:entrenar", "data_analyst")
    assert "Pasos: Nuevo modelo → trainModel" in text
    assert use_case.describe("task:entrenar", "fraud_analyst") == ""
    assert use_case.describe("nope", "data_analyst") == ""
    ref = use_case.reference_for("task:entrenar", "data_analyst")
    assert (
        ref is not None and ref.path == "/modelos" and ref.label == "Entrenar un modelo"
    )
    assert use_case.reference_for("view:/alerta/$id", "") is None  # dynamic route
    assert use_case.node_ref("view:/modelos", "fraud_analyst") is None
