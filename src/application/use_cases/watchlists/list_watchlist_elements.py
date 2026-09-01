from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.watchlist_port import WatchlistRepository


@dataclass(frozen=True)
class WatchlistElementsPage:
    values: list[str]
    next_cursor: str | None


class ListWatchlistElementsUseCase:
    """Paginated on purpose - a gigantic watchlist can't be handed back in
    one response, and the admin UI renders it a page at a time."""

    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(
        self, watchlist_id: str, *, limit: int = 100, cursor: str | None = None
    ) -> WatchlistElementsPage:
        values, next_cursor = self._watchlists.list_elements(
            watchlist_id, limit=limit, cursor=cursor
        )
        return WatchlistElementsPage(values=values, next_cursor=next_cursor)
