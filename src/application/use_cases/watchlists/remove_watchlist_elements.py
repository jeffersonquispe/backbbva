from __future__ import annotations

from src.application.ports.watchlist_port import WatchlistRepository


class RemoveWatchlistElementsUseCase:
    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(self, watchlist_id: str, values: list[str]) -> int:
        return self._watchlists.remove_elements(watchlist_id, values)
