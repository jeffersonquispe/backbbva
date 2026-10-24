from __future__ import annotations

from typing import Protocol


class AgentProjectTools(Protocol):
    """Read-only lookups over the ARIA project map, scoped to one chat turn."""

    def search_project(self, query: str) -> str: ...

    def describe_node(self, node_id: str) -> str: ...
