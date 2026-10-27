from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass

from src.application.ports.project_graph_port import ProjectGraphRepository
from src.application.ports.project_graph_semantic_port import (
    ProjectGraphSemanticSearch,
)
from src.domain.project_graph.entities import GraphNode, NodeKind, ProjectGraph
from src.domain.project_graph.index import tokenize

__all__ = [
    "ProjectContext",
    "ProjectNodeRef",
    "ProjectReference",
    "RetrieveProjectContextInput",
    "RetrieveProjectContextUseCase",
    "tokenize",
]

SEED_COUNT = 6
BLOCKED_PROBE = 3
HOPS = 2
HOP_DECAY = 0.55
PAGE_SEED_FLOOR = 0.6
HISTORY_MESSAGES = 2
HISTORY_WEIGHT = 0.4
RRF_K = 60
SEMANTIC_CANDIDATES = 20
SUGGESTION_MIN_SEED = 0.5
MAX_SUGGESTIONS = 2
MAX_KEYWORDS_RENDERED = 5
MAX_EDGES_RENDERED = 24
MAX_TASKS_ON_PAGE = 6
MAX_STEPS_RENDERED = 6

BLOCKED_NOTE = (
    "Nota: lo que pregunta existe en ARIA, pero su rol no tiene acceso a esa "
    "vista o acción; dilo sin describir cómo usarla."
)
RELATION_WEIGHT = {
    "renders": 0.8,
    "offers": 0.7,
    "calls": 0.6,
    "requests": 0.6,
    "handled_by": 0.5,
    "navigates_to": 0.5,
    "uses_asset": 0.5,
    "belongs_to": 0.3,
    "starts_at": 0.8,
    "involves": 0.8,
    "manifested_in": 0.6,
    "can_open": 0.4,
    "grants": 0.3,
    "requires": 0.4,
    "uses_port": 0.4,
    "implemented_by": 0.4,
}
# Cap per kind so a broad query cannot fill the context with one node type.
KIND_QUOTA = {
    NodeKind.TASK: 3,
    NodeKind.CONCEPT: 2,
    NodeKind.VIEW: 3,
    NodeKind.COMPONENT: 4,
    NodeKind.ACTION: 4,
    NodeKind.API_CALL: 3,
    NodeKind.ENDPOINT: 3,
    NodeKind.USE_CASE: 2,
    NodeKind.PORT: 1,
    NodeKind.ADAPTER: 1,
    NodeKind.RESOURCE: 2,
    NodeKind.ASSET: 2,
    NodeKind.ROLE: 1,
    NodeKind.PERMISSION: 1,
}
KIND_LABEL = {
    NodeKind.TASK: "Tareas",
    NodeKind.CONCEPT: "Conceptos",
    NodeKind.VIEW: "Vistas",
    NodeKind.COMPONENT: "Componentes",
    NodeKind.ACTION: "Acciones del usuario",
    NodeKind.API_CALL: "Llamadas del frontend",
    NodeKind.ENDPOINT: "Endpoints",
    NodeKind.USE_CASE: "Casos de uso",
    NodeKind.PORT: "Puertos",
    NodeKind.ADAPTER: "Adaptadores",
    NodeKind.RESOURCE: "Recursos de API",
    NodeKind.ASSET: "Activos",
    NodeKind.ROLE: "Roles",
    NodeKind.PERMISSION: "Permisos",
}


@dataclass(frozen=True)
class RetrieveProjectContextInput:
    query: str
    page_path: str = ""
    # Server-side role of the user; hides views/tasks/endpoints they cannot reach.
    role: str = ""
    # Earlier user messages (oldest first); they only add weak extra query terms.
    history: tuple[str, ...] = ()
    max_nodes: int = 16
    max_chars: int = 3_500


@dataclass(frozen=True)
class ProjectNodeRef:
    node_id: str
    kind: str
    label: str


@dataclass(frozen=True)
class ProjectReference:
    """A place the user can open: a view or the entry view of a task."""

    node_id: str
    kind: str
    label: str
    path: str


@dataclass(frozen=True)
class ProjectContext:
    text: str
    node_ids: tuple[str, ...] = ()
    nodes: tuple[ProjectNodeRef, ...] = ()
    # Navigable nodes in relevance order (current page excluded) and the subset
    # backed by a strong lexical match, used as a fallback when the model cites none.
    references: tuple[ProjectReference, ...] = ()
    suggested: tuple[ProjectReference, ...] = ()


DEFINITION_RE = re.compile(
    r"^\W*(?:que|qué)\s+(?:es|son|significa|quiere decir)\b|\b(?:define|definicion|definición|significado)\b",
    re.IGNORECASE,
)
HOWTO_RE = re.compile(
    r"\b(?:como|cómo|donde|dónde|puedo|quiero|necesito|pasos)\b", re.IGNORECASE
)
CONCEPT_BOOST = 1.7
TASK_BOOST = 1.3


def _intent_boosts(query: str) -> dict[NodeKind, float]:
    """ "¿Qué es X?" prefers concepts; "¿cómo/dónde…?" prefers tasks."""
    if DEFINITION_RE.search(query):
        return {NodeKind.CONCEPT: CONCEPT_BOOST}
    if HOWTO_RE.search(query):
        return {NodeKind.TASK: TASK_BOOST}
    return {}


class RetrieveProjectContextUseCase:
    """Graph-RAG over the project graph.

    1. Seeding: BM25 over node name/keywords/description (current message plus
       a little weight from the previous ones), optionally fused with
       embedding similarity by reciprocal-rank fusion; the view the user is on
       is always a seed.
    2. Role filter: nodes the user's role cannot reach are dropped up front.
    3. Spreading activation over typed edges (hub-damped, ``HOPS`` hops), so a
       question about a button also surfaces its view, task, API call,
       endpoint and use case.
    4. Per-kind quotas, then a compact text with the current view, its tasks,
       the selected nodes and their connections.
    """

    def __init__(
        self,
        *,
        graph: ProjectGraphRepository,
        semantic: ProjectGraphSemanticSearch | None = None,
    ) -> None:
        self._graph = graph
        self._semantic = semantic

    # -- public -----------------------------------------------------------

    def execute(self, request: RetrieveProjectContextInput) -> ProjectContext:
        graph = self._graph.load()
        if not graph.nodes:
            return ProjectContext(text="")
        hidden = graph.hidden_for(request.role)
        page_view = self._page_view(graph, request.page_path, hidden)
        lexical, blocked = self._lexical_seeds(graph, request, hidden)
        seeds = self._fuse_with_semantic(lexical, request.query, hidden)
        if page_view:
            seeds[page_view] = max(seeds.get(page_view, 0.0), PAGE_SEED_FLOOR)
        if not seeds:
            return ProjectContext(
                text=self._blocked_note(request.role) if blocked else ""
            )
        activation = self._spread(graph, seeds, hidden)
        selected = self._select(graph, activation, request.max_nodes)
        references = self._references(graph, selected, request.page_path)
        strong = {
            node_id for node_id, score in seeds.items() if score >= SUGGESTION_MIN_SEED
        }
        suggested = tuple(ref for ref in references if ref.node_id in strong)[
            :MAX_SUGGESTIONS
        ]
        return ProjectContext(
            text=self._render(graph, selected, page_view, request, blocked),
            node_ids=tuple(node.node_id for node in selected),
            nodes=tuple(
                ProjectNodeRef(node.node_id, node.kind.value, node.display)
                for node in selected
            ),
            references=references,
            suggested=suggested if lexical else (),
        )

    @staticmethod
    def _blocked_note(role: str) -> str:
        return f"Rol del usuario: {role}\n{BLOCKED_NOTE}" if role else BLOCKED_NOTE

    def describe(self, node_id: str, role: str = "") -> str:
        """Details of one node and its neighbours; empty if unknown or hidden."""
        graph = self._graph.load()
        node = graph.nodes.get(node_id)
        hidden = graph.hidden_for(role)
        if node is None or node_id in hidden:
            return ""
        lines = [f"{node.kind.value}: {node.display}"]
        if node.description:
            lines.append(node.description)
        if node.keywords:
            lines.append("Textos: " + "; ".join(node.keywords[:12]))
        if node.kind is NodeKind.TASK:
            steps = [t for t in graph.outgoing(node_id, "involves") if t not in hidden]
            if steps:
                lines.append(
                    "Pasos: " + " → ".join(graph.nodes[t].display for t in steps)
                )
        grouped: dict[str, list[str]] = defaultdict(list)
        for other, relation in graph.adjacency[node_id]:
            if other not in hidden and len(grouped[relation]) < 8:
                grouped[relation].append(graph.nodes[other].display)
        for relation, names in sorted(grouped.items()):
            lines.append(f"{relation}: " + "; ".join(names))
        return "\n".join(lines)[:2_000]

    def node_ref(self, node_id: str, role: str = "") -> ProjectNodeRef | None:
        graph = self._graph.load()
        node = graph.nodes.get(node_id)
        if node is None or node_id in graph.hidden_for(role):
            return None
        return ProjectNodeRef(node.node_id, node.kind.value, node.display)

    def is_visible(self, node_id: str, role: str) -> bool:
        graph = self._graph.load()
        return node_id in graph.nodes and node_id not in graph.hidden_for(role)

    def reference_for(self, node_id: str, role: str = "") -> ProjectReference | None:
        graph = self._graph.load()
        node = graph.nodes.get(node_id)
        if node is None or node_id in graph.hidden_for(role):
            return None
        return self._reference(graph, node)

    # -- seeding ----------------------------------------------------------

    @staticmethod
    def _page_view(
        graph: ProjectGraph, page_path: str, hidden: frozenset[str]
    ) -> str | None:
        path = "/" + page_path.strip().strip("/") if page_path.strip() else ""
        best: str | None = None
        for node_id, node in graph.nodes.items():
            if node.kind is not NodeKind.VIEW or node_id in hidden:
                continue
            view_path = node.name
            if path == view_path or path.startswith(view_path.rstrip("/") + "/"):
                if best is None or len(view_path) > len(graph.nodes[best].name):
                    best = node_id
        return best

    @staticmethod
    def _lexical_seeds(
        graph: ProjectGraph,
        request: RetrieveProjectContextInput,
        hidden: frozenset[str],
    ) -> tuple[dict[str, float], bool]:
        """Seeds visible to the role, and whether the best matches were hidden."""
        weights: dict[str, float] = defaultdict(float)
        for token in tokenize(request.query):
            weights[token] = 1.0
        for message in request.history[-HISTORY_MESSAGES:]:
            for token in tokenize(message):
                weights[token] = max(weights[token], HISTORY_WEIGHT)
        boosts = _intent_boosts(request.query)
        ranked = sorted(
            (
                (node_id, score * boosts.get(graph.nodes[node_id].kind, 1.0))
                for node_id, score in graph.index.score(dict(weights)).items()
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        # A hidden node can match incidental words (for example, an "E2E"
        # test endpoint) while a directly relevant action is available to the
        # role. Only claim the request is blocked when its strongest hidden
        # view/task/action outranks every visible view/task/action match.
        relevant_kinds = {NodeKind.VIEW, NodeKind.TASK, NodeKind.ACTION}
        hidden_relevant = [
            score
            for node_id, score in ranked[:BLOCKED_PROBE]
            if node_id in hidden and graph.nodes[node_id].kind in relevant_kinds
        ]
        visible_relevant = [
            score
            for node_id, score in ranked
            if node_id not in hidden and graph.nodes[node_id].kind in relevant_kinds
        ]
        blocked = bool(hidden_relevant) and max(hidden_relevant) > max(
            visible_relevant, default=0.0
        )
        top = [item for item in ranked if item[0] not in hidden][:SEED_COUNT]
        if not top:
            return {}, blocked
        best = top[0][1]
        return {node_id: score / best for node_id, score in top}, blocked

    def _fuse_with_semantic(
        self, lexical: dict[str, float], query: str, hidden: frozenset[str]
    ) -> dict[str, float]:
        if self._semantic is None or not query.strip():
            return dict(lexical)
        try:
            ranked = [
                node_id
                for node_id in self._semantic.rank(query, SEMANTIC_CANDIDATES)
                if node_id not in hidden
            ]
        except Exception:  # noqa: BLE001 - embeddings are optional; BM25 still answers
            return dict(lexical)
        fused: dict[str, float] = defaultdict(float)
        for rank, node_id in enumerate(sorted(lexical, key=lexical.get, reverse=True)):  # type: ignore[arg-type]
            fused[node_id] += 1 / (RRF_K + rank + 1)
        for rank, node_id in enumerate(ranked):
            fused[node_id] += 1 / (RRF_K + rank + 1)
        top = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:SEED_COUNT]
        best = top[0][1] if top else 0.0
        return {node_id: score / best for node_id, score in top} if best else {}

    # -- spreading / selection --------------------------------------------

    @staticmethod
    def _spread(
        graph: ProjectGraph, seeds: dict[str, float], hidden: frozenset[str]
    ) -> dict[str, float]:
        adjacency = graph.adjacency
        activation = dict(seeds)
        frontier = dict(seeds)
        for _ in range(HOPS):
            reached: dict[str, float] = {}
            for node_id, energy in frontier.items():
                neighbors = adjacency[node_id]
                # Hub damping: a node wired to everything spreads little.
                damping = 1 / math.log2(2 + len(neighbors))
                for other, relation in neighbors:
                    if other in hidden:
                        continue
                    gain = (
                        energy
                        * HOP_DECAY
                        * RELATION_WEIGHT.get(relation, 0.3)
                        * damping
                        * 2
                        # Shared UI (DataTable, layouts) must not crowd out
                        # the specific nodes the question is about.
                        * min(1.0, 2 / math.log2(2 + len(adjacency[other])))
                    )
                    if gain > activation.get(other, 0.0) and gain > reached.get(
                        other, 0.0
                    ):
                        reached[other] = gain
            activation.update(reached)
            frontier = reached
        return activation

    @staticmethod
    def _select(
        graph: ProjectGraph, activation: dict[str, float], max_nodes: int
    ) -> list[GraphNode]:
        chosen: list[GraphNode] = []
        per_kind: dict[NodeKind, int] = defaultdict(int)
        for node_id, _ in sorted(
            activation.items(), key=lambda item: (-item[1], item[0])
        ):
            node = graph.nodes[node_id]
            if per_kind[node.kind] >= KIND_QUOTA.get(node.kind, 2):
                continue
            per_kind[node.kind] += 1
            chosen.append(node)
            if len(chosen) >= max_nodes:
                break
        return chosen

    # -- references -------------------------------------------------------

    @staticmethod
    def _reference(graph: ProjectGraph, node: GraphNode) -> ProjectReference | None:
        view: GraphNode | None = None
        if node.kind is NodeKind.VIEW:
            view = node
        elif node.kind is NodeKind.TASK:
            starts = graph.outgoing(node.node_id, "starts_at")
            view = graph.nodes.get(starts[0]) if starts else None
        if view is None or "$" in view.name:
            return None  # dynamic routes need an id the user has to pick first
        return ProjectReference(node.node_id, node.kind.value, node.display, view.name)

    def _references(
        self, graph: ProjectGraph, selected: list[GraphNode], page_path: str
    ) -> tuple[ProjectReference, ...]:
        current = "/" + page_path.strip().strip("/") if page_path.strip() else ""
        found: list[ProjectReference] = []
        for node in selected:
            ref = self._reference(graph, node)
            if ref is None or ref.path == current:
                continue
            found.append(ref)
        return tuple(found)

    # -- rendering --------------------------------------------------------

    @staticmethod
    def _render(
        graph: ProjectGraph,
        selected: list[GraphNode],
        page_view: str | None,
        request: RetrieveProjectContextInput,
        blocked: bool = False,
    ) -> str:
        hidden = graph.hidden_for(request.role)
        lines: list[str] = []
        if request.role:
            lines.append(f"Rol del usuario: {request.role}")
        if blocked:
            lines.append(BLOCKED_NOTE)
        if page_view:
            view = graph.nodes[page_view]
            lines.append(
                f"Vista actual: {view.display} ({view.name}) — {view.description}"
            )
            tasks = [
                graph.nodes[t].name
                for t in graph.incoming(page_view, "starts_at")
                if t not in hidden
            ][:MAX_TASKS_ON_PAGE]
            if tasks:
                lines.append("Tareas posibles aquí: " + "; ".join(tasks))
        by_kind: dict[NodeKind, list[GraphNode]] = defaultdict(list)
        for node in selected:
            by_kind[node.kind].append(node)
        for kind in KIND_LABEL:
            nodes = by_kind.get(kind)
            if not nodes:
                continue
            lines.append(f"{KIND_LABEL[kind]}:")
            for node in nodes:
                extra = [word for word in node.keywords if word != node.name][
                    :MAX_KEYWORDS_RENDERED
                ]
                detail = f" — {node.description}" if node.description else ""
                words = (
                    f" [{'; '.join(extra)}]"
                    if extra and kind not in {NodeKind.TASK, NodeKind.CONCEPT}
                    else ""
                )
                lines.append(f"- [{node.node_id}] {node.display}{detail}{words}")
                if kind is NodeKind.TASK:
                    steps = [
                        graph.nodes[t].display
                        for t in graph.outgoing(node.node_id, "involves")
                        if t not in hidden
                    ][:MAX_STEPS_RENDERED]
                    if steps:
                        lines.append("  pasos: " + " → ".join(steps))
        ids = {node.node_id for node in selected}
        connections = [
            f"{graph.nodes[edge.source].display} -{edge.relation}-> {graph.nodes[edge.target].display}"
            for edge in graph.edges
            if edge.source in ids
            and edge.target in ids
            and edge.relation not in {"involves", "starts_at"}
        ][:MAX_EDGES_RENDERED]
        if connections:
            lines.append("Conexiones:")
            lines.extend(f"- {item}" for item in connections)
        text = "\n".join(lines)
        limit = request.max_chars
        return text if len(text) <= limit else text[: limit - 1] + "…"
