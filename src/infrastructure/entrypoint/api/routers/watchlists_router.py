from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.watchlist_port import Watchlist, WatchlistType
from src.application.use_cases.watchlists.check_watchlist_membership import (
    CheckWatchlistMembershipUseCase,
)
from src.application.use_cases.watchlists.create_watchlist import CreateWatchlistUseCase
from src.application.use_cases.watchlists.delete_watchlist import DeleteWatchlistUseCase
from src.application.use_cases.watchlists.list_watchlists import ListWatchlistsUseCase
from src.application.use_cases.watchlists.update_watchlist import (
    UpdateWatchlistUseCase,
    WatchlistNotFoundError,
)
from src.infrastructure.entrypoint.api.factories.watchlist_factory import (
    get_check_watchlist_membership_use_case,
    get_create_watchlist_use_case,
    get_delete_watchlist_use_case,
    get_list_watchlists_use_case,
    get_update_watchlist_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CheckWatchlistMembershipRequest,
    CheckWatchlistMembershipResponse,
    CreateWatchlistRequest,
    UpdateWatchlistRequest,
    WatchlistMatchSchema,
    WatchlistSchema,
)

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


@router.get("", response_model=list[WatchlistSchema])
def list_watchlists(
    use_case: Annotated[ListWatchlistsUseCase, Depends(get_list_watchlists_use_case)],
    list_type: WatchlistType | None = None,
    active_only: bool = False,
):
    return [
        _to_schema(entry)
        for entry in use_case.execute(list_type=list_type, active_only=active_only)
    ]


@router.post("", response_model=WatchlistSchema, status_code=status.HTTP_201_CREATED)
def create_watchlist(
    request: CreateWatchlistRequest,
    use_case: Annotated[CreateWatchlistUseCase, Depends(get_create_watchlist_use_case)],
):
    return _to_schema(
        use_case.execute(
            request.name, request.description, request.list_type, request.elements
        )
    )


@router.patch("/{watchlist_id}", response_model=WatchlistSchema)
def update_watchlist(
    watchlist_id: str,
    request: UpdateWatchlistRequest,
    use_case: Annotated[UpdateWatchlistUseCase, Depends(get_update_watchlist_use_case)],
):
    try:
        watchlist = use_case.execute(
            watchlist_id,
            name=request.name,
            description=request.description,
            elements=request.elements,
            active=request.active,
        )
    except WatchlistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(watchlist)


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(
    watchlist_id: str,
    use_case: Annotated[DeleteWatchlistUseCase, Depends(get_delete_watchlist_use_case)],
):
    use_case.execute(watchlist_id)


@router.post("/check-membership", response_model=CheckWatchlistMembershipResponse)
def check_watchlist_membership(
    request: CheckWatchlistMembershipRequest,
    use_case: Annotated[
        CheckWatchlistMembershipUseCase, Depends(get_check_watchlist_membership_use_case)
    ],
):
    matches = use_case.execute(request.list_type, request.value)
    return CheckWatchlistMembershipResponse(
        is_member=len(matches) > 0,
        matches=[
            WatchlistMatchSchema(watchlist_id=m.watchlist_id, watchlist_name=m.watchlist_name)
            for m in matches
        ],
    )


def _to_schema(watchlist: Watchlist) -> WatchlistSchema:
    return WatchlistSchema(
        id=watchlist.id,
        name=watchlist.name,
        description=watchlist.description,
        list_type=watchlist.list_type,
        elements=watchlist.elements,
        active=watchlist.active,
        created_at=watchlist.created_at,
        updated_at=watchlist.updated_at,
    )
