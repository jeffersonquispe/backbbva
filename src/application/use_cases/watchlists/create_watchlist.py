from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.watchlist_port import (
    Watchlist,
    WatchlistRepository,
    WatchlistType,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class CreateWatchlistUseCase:
    def __init__(
        self,
        watchlist_repository: WatchlistRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._watchlists = watchlist_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self,
        name: str,
        description: str,
        list_type: WatchlistType,
        elements: list[str] | None = None,
    ) -> Watchlist:
        now = self._clock.now()
        watchlist = self._watchlists.create(
            Watchlist(
                id=str(self._id_generator.new_id()),
                name=name,
                description=description,
                list_type=list_type,
                created_at=now,
                updated_at=now,
            )
        )
        if elements:
            watchlist.element_count = self._watchlists.add_elements(
                watchlist.id, elements
            )
        return watchlist
