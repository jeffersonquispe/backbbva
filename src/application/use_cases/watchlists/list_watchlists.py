from __future__ import annotations

from src.application.ports.watchlist_port import (
    Watchlist,
    WatchlistRepository,
    WatchlistType,
)


class ListWatchlistsUseCase:
    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(
        self,
        *,
        list_type: WatchlistType | None = None,
        active_only: bool = False,
    ) -> list[Watchlist]:
        return self._watchlists.list(list_type=list_type, active_only=active_only)
