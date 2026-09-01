from __future__ import annotations

from src.application.ports.watchlist_port import Watchlist, WatchlistRepository


class GetWatchlistUseCase:
    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(self, watchlist_id: str) -> Watchlist | None:
        return self._watchlists.get(watchlist_id)
