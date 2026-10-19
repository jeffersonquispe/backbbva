from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class WatchlistType(StrEnum):
    BLACKLIST = "blacklist"
    WHITELIST = "whitelist"


@dataclass
class Watchlist:
    # A named, described set of elements evaluated for membership - a
    # blacklist and a whitelist are the same shape, only `list_type`
    # differs in how a caller should interpret a match (deny vs. allow).
    # Elements are NOT a field here - a "gigantic" list (tens of thousands+
    # of values) doesn't fit in one Dynamo item (400KB cap) and shouldn't be
    # loaded wholesale on every read. They live in their own
    # (watchlist_id, value) keyed store - see add_elements/list_elements/
    # elements_containing below. `element_count` is a read-time summary,
    # not a stored field.
    id: str
    name: str
    description: str
    list_type: WatchlistType
    created_at: datetime
    updated_at: datetime
    element_count: int = 0
    active: bool = True


class WatchlistRepository(Protocol):
    def create(self, watchlist: Watchlist) -> Watchlist: ...

    def get(self, watchlist_id: str) -> Watchlist | None: ...

    def list(
        self,
        *,
        list_type: WatchlistType | None = None,
        active_only: bool = False,
    ) -> list[Watchlist]: ...

    def update(
        self,
        watchlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> Watchlist | None: ...

    def delete(self, watchlist_id: str) -> None: ...

    # --- Elements (the gigantic part) --------------------------------
    # Values are normalized (strip + casefold) for storage/matching, same
    # normalization CheckWatchlistMembershipUseCase used to do ad hoc.

    def add_elements(self, watchlist_id: str, values: builtins.list[str]) -> int:
        """Upserts values into the watchlist. Returns the number of
        distinct normalized values submitted (dedup is transparent -
        adding an existing value is a no-op, not an error)."""
        ...

    def remove_elements(self, watchlist_id: str, values: builtins.list[str]) -> int:
        """Returns the number of distinct normalized values removed."""
        ...

    def count_elements(self, watchlist_id: str) -> int: ...

    def list_elements(
        self,
        watchlist_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[builtins.list[str], str | None]:
        """Paginated - a gigantic list can't be returned in one response.
        Returns (page of values in their original casing, next cursor or
        None if this was the last page)."""
        ...

    def elements_containing(
        self, watchlist_ids: builtins.list[str], value: str
    ) -> set[str]:
        """Given a small set of watchlist ids (the active watchlists of one
        list_type - not the elements themselves), returns the subset whose
        element set contains `value`. One batch lookup regardless of how
        large each watchlist is - the hot-path membership check fans out
        over watchlist COUNT, never element COUNT."""
        ...
