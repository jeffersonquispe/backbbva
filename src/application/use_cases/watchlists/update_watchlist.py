from __future__ import annotations

from src.application.ports.watchlist_port import Watchlist, WatchlistRepository


class WatchlistNotFoundError(Exception):
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
    ) -> Watchlist:
        updated = self._watchlists.update(
            watchlist_id,
            name=name,
            description=description,
            active=active,
        )
        if updated is None:
            raise WatchlistNotFoundError(f"Watchlist not found: {watchlist_id}")
        return updated
