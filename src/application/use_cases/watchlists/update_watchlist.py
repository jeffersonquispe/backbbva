from __future__ import annotations

from datetime import datetime

from src.application.errors import NotFoundError
from src.application.ports.watchlist_port import Watchlist, WatchlistRepository


class WatchlistNotFoundError(NotFoundError):
    pass


class UpdateWatchlistUseCase:
    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(
        self,
        watchlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
        expected_updated_at: datetime | None = None,
    ) -> Watchlist:
        updated = self._watchlists.update(
            watchlist_id,
            name=name,
            description=description,
            active=active,
            expected_updated_at=expected_updated_at,
        )
        if updated is None:
            raise WatchlistNotFoundError(f"Watchlist not found: {watchlist_id}")
        return updated
