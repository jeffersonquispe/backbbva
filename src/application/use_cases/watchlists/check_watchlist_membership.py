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

    Hot-path call (the agent checks this per alert): fans out over the
    number of active watchlists of this type (small, a handful in
    practice), never over the number of elements in any one of them -
    elements_containing does a single batched key lookup regardless of
    whether a watchlist holds ten or ten million values.
    """

    def __init__(self, watchlist_repository: WatchlistRepository) -> None:
        self._watchlists = watchlist_repository

    def execute(self, list_type: WatchlistType, value: str) -> list[WatchlistMatch]:
        candidates = self._watchlists.list(list_type=list_type, active_only=True)
        if not candidates:
            return []
        hit_ids = self._watchlists.elements_containing(
            [w.id for w in candidates], value
        )
        return [
            WatchlistMatch(watchlist_id=w.id, watchlist_name=w.name)
            for w in candidates
            if w.id in hit_ids
        ]
