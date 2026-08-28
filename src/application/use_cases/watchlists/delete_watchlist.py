from __future__ import annotations

from src.application.ports.watchlist_port import WatchlistRepository


class DeleteWatchlistUseCase:
    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(self, watchlist_id: str) -> None:
        self._watchlists.delete(watchlist_id)
