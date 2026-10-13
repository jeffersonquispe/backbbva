from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.ports.watchlist_port import (
    Watchlist,
    WatchlistRepository,
    WatchlistType,
)


class CreateWatchlistUseCase:
    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(
        self,
        name: str,
        description: str,
        list_type: WatchlistType,
        elements: list[str] | None = None,
    ) -> Watchlist:
        now = datetime.now(UTC)
        watchlist = self._watchlists.create(
            Watchlist(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                list_type=list_type,
                created_at=now,
                updated_at=now,
            )
        )
        if elements:
            watchlist.element_count = self._watchlists.add_elements(
                watchlist.id, elements
            )
        return watchlist
