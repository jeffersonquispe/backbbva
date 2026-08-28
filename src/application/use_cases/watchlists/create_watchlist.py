from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
        now = datetime.now(timezone.utc)
        return self._watchlists.create(
            Watchlist(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                list_type=list_type,
                elements=elements or [],
                created_at=now,
                updated_at=now,
            )
        )
