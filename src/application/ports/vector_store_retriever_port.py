from __future__ import annotations

from typing import Protocol


class VectorStoreRetriever(Protocol):
    """Adapter boundary for a promoted, already scoped vector store."""

    def search(
        self, query: str, *, asset_type: str, top_k: int
    ) -> list[dict[str, object]]: ...
