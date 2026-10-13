from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.application.ports.watchlist_port import WatchlistType

# --- Watchlists (blacklist / whitelist) ------------------------------------


class WatchlistSchema(BaseModel):
    id: str
    name: str
    description: str
    list_type: WatchlistType
    element_count: int
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateWatchlistRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=1000)
    list_type: WatchlistType
    # Small inline seed list only - bulk loads go through the
    # /elements/import file upload endpoint instead of one giant JSON body.
    elements: list[str] = Field(default_factory=list)


class UpdateWatchlistRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    active: bool | None = None


class WatchlistElementsPageSchema(BaseModel):
    values: list[str]
    next_cursor: str | None = None


class AddWatchlistElementsRequest(BaseModel):
    values: list[str] = Field(..., min_length=1)


class AddWatchlistElementsResponse(BaseModel):
    added: int


class RemoveWatchlistElementsRequest(BaseModel):
    values: list[str] = Field(..., min_length=1)


class RemoveWatchlistElementsResponse(BaseModel):
    removed: int


class CheckWatchlistMembershipRequest(BaseModel):
    list_type: WatchlistType
    value: str = Field(..., min_length=1)


class WatchlistMatchSchema(BaseModel):
    watchlist_id: str
    watchlist_name: str


class CheckWatchlistMembershipResponse(BaseModel):
    is_member: bool
    matches: list[WatchlistMatchSchema]
