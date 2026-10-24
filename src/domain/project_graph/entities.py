from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property

from src.domain.project_graph.index import ProjectGraphIndex


class NodeKind(StrEnum):
    VIEW = "view"
    COMPONENT = "component"
    ACTION = "action"
    API_CALL = "api_call"
    ENDPOINT = "endpoint"
    USE_CASE = "use_case"
    PORT = "port"
    ADAPTER = "adapter"
    RESOURCE = "resource"
    ASSET = "asset"
    ROLE = "role"
    PERMISSION = "permission"
    TASK = "task"
    CONCEPT = "concept"


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: NodeKind
    name: str
    description: str = ""
    keywords: tuple[str, ...] = ()
    # Short human label shown to users (views: "Biblioteca"); falls back to name.
    label: str = ""

    @property
    def display(self) -> str:
        return self.label or self.name


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    position: int = 0


@dataclass(frozen=True)
class ProjectGraph:
    """Typed property graph of ARIA: what exists and how it connects."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: tuple[GraphEdge, ...] = ()

    @cached_property
    def adjacency(self) -> dict[str, list[tuple[str, str]]]:
        """node id -> [(neighbor id, relation)], both directions."""
        found: dict[str, list[tuple[str, str]]] = {
            node_id: [] for node_id in self.nodes
        }
        for edge in self.edges:
            if edge.source in self.nodes and edge.target in self.nodes:
                found[edge.source].append((edge.target, edge.relation))
                found[edge.target].append((edge.source, edge.relation))
        return found

    @cached_property
    def index(self) -> ProjectGraphIndex:
        return ProjectGraphIndex.build(
            {
                node_id: (node.name, node.keywords, node.description)
                for node_id, node in self.nodes.items()
            }
        )

    @cached_property
    def _by_source(self) -> dict[tuple[str, str], list[GraphEdge]]:
        found: dict[tuple[str, str], list[GraphEdge]] = {}
        for edge in self.edges:
            found.setdefault((edge.source, edge.relation), []).append(edge)
        return found

    @cached_property
    def _by_target(self) -> dict[tuple[str, str], list[GraphEdge]]:
        found: dict[tuple[str, str], list[GraphEdge]] = {}
        for edge in self.edges:
            found.setdefault((edge.target, edge.relation), []).append(edge)
        return found

    @cached_property
    def _hidden_by_role(self) -> dict[str, frozenset[str]]:
        return {}

    def outgoing(self, node_id: str, relation: str) -> list[str]:
        """Targets of ``relation`` edges leaving ``node_id``, ordered by position."""
        edges = self._by_source.get((node_id, relation), [])
        return [edge.target for edge in sorted(edges, key=lambda e: e.position)]

    def incoming(self, node_id: str, relation: str) -> list[str]:
        return [edge.source for edge in self._by_target.get((node_id, relation), [])]

    def hidden_for(self, role: str) -> frozenset[str]:
        """Nodes the ``role`` cannot reach, so they are never suggested to it.

        Views come from the frontend's role navigation, endpoints from the
        permissions they require, and everything that only exists behind a
        hidden view/endpoint (actions, tasks, API calls, use cases) follows.
        An unknown or empty role hides nothing: the API still enforces access.
        """
        role_id = f"role:{role}"
        if not role or role_id not in self.nodes:
            return frozenset()
        cached = self._hidden_by_role.get(role)
        if cached is None:
            cached = self._compute_hidden(role_id)
            self._hidden_by_role[role] = cached
        return cached

    def _compute_hidden(self, role_id: str) -> frozenset[str]:
        gated_views = {e.target for e in self.edges if e.relation == "can_open"}
        allowed_views = set(self.outgoing(role_id, "can_open"))
        granted = set(self.outgoing(role_id, "grants"))
        by_kind: dict[NodeKind, list[str]] = {}
        for node_id, node in self.nodes.items():
            by_kind.setdefault(node.kind, []).append(node_id)

        hidden: set[str] = {v for v in gated_views if v not in allowed_views}
        for node_id in by_kind.get(NodeKind.ENDPOINT, []):
            required = set(self.outgoing(node_id, "requires"))
            if required and not required <= granted:
                hidden.add(node_id)

        def reach(roots: list[str]) -> set[str]:
            seen, stack = set(roots), list(roots)
            while stack:
                for target in self.outgoing(stack.pop(), "renders"):
                    if target not in seen:
                        seen.add(target)
                        stack.append(target)
            return seen

        def all_hidden(sources: list[str]) -> bool:
            return bool(sources) and all(item in hidden for item in sources)

        for _ in range(4):  # views and components unlock each other; settle fast
            before = len(hidden)
            views = by_kind.get(NodeKind.VIEW, [])
            for view in views:
                if view not in hidden and all_hidden(
                    self.incoming(view, "navigates_to")
                ):
                    hidden.add(view)
            visible = reach([v for v in views if v not in hidden])
            under_hidden = reach([v for v in views if v in hidden])
            hidden |= {
                n
                for n in under_hidden - visible
                if self.nodes[n].kind is NodeKind.COMPONENT
            }
            if len(hidden) == before:
                break

        for node_id in by_kind.get(NodeKind.API_CALL, []):
            if all_hidden(self.incoming(node_id, "calls")) or all_hidden(
                self.outgoing(node_id, "requests")
            ):
                hidden.add(node_id)
        for node_id in by_kind.get(NodeKind.ENDPOINT, []):
            if all_hidden(self.incoming(node_id, "requests")):
                hidden.add(node_id)
        for node_id in by_kind.get(NodeKind.ACTION, []):
            if any(owner in hidden for owner in self.incoming(node_id, "offers")):
                hidden.add(node_id)
        for node_id in by_kind.get(NodeKind.TASK, []):
            if any(view in hidden for view in self.outgoing(node_id, "starts_at")):
                hidden.add(node_id)
        for node_id in by_kind.get(NodeKind.USE_CASE, []):
            if all_hidden(self.incoming(node_id, "handled_by")):
                hidden.add(node_id)
        return frozenset(hidden)
