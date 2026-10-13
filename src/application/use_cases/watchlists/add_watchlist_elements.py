from __future__ import annotations

from src.application.errors import NotFoundError
from src.application.ports.watchlist_port import WatchlistRepository


class WatchlistNotFoundError(NotFoundError):
    pass


class AddWatchlistElementsUseCase:
    """Also the bulk-import path - a CSV/text-file upload is parsed into a
    list[str] by the router (an infra concern) and lands here the same as a
    single manual addition. BatchWriteItem in the repository keeps this
    cheap regardless of how many values are submitted at once."""

    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(self, watchlist_id: str, values: list[str]) -> int:
        if self._watchlists.get(watchlist_id) is None:
            raise WatchlistNotFoundError(f"Watchlist not found: {watchlist_id}")
        return self._watchlists.add_elements(watchlist_id, values)
