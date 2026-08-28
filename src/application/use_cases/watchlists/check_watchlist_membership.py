from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.watchlist_port import WatchlistRepository, WatchlistType


@dataclass(frozen=True)
class WatchlistMatch:
    watchlist_id: str
    watchlist_name: str


class CheckWatchlistMembershipUseCase:
    """Evaluates whether `value` belongs to any active watchlist of
    `list_type` - a blacklist hit and a whitelist hit are the same
    membership check, only the caller's interpretation of a match differs.
    """

    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(self, list_type: WatchlistType, value: str) -> list[WatchlistMatch]:
        normalized = value.strip().casefold()
        matches = []
        for watchlist in self._watchlists.list(list_type=list_type, active_only=True):
            if normalized in {element.strip().casefold() for element in watchlist.elements}:
                matches.append(
                    WatchlistMatch(watchlist_id=watchlist.id, watchlist_name=watchlist.name)
                )
        return matches
