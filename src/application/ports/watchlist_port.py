from __future__ import annotations

from dataclasses import dataclass, field
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
    id: str
    name: str
    description: str
    list_type: WatchlistType
    created_at: datetime
    updated_at: datetime
    elements: list[str] = field(default_factory=list)
    active: bool = True


class WatchlistRepository(Protocol):
    def create(self, watchlist: Watchlist) -> Watchlist: ...

    def get(self, watchlist_id: str) -> Watchlist | None:
        ...

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
        elements: list[str] | None = None,
        active: bool | None = None,
    ) -> Watchlist | None: ...

    def delete(self, watchlist_id: str) -> None: ...
