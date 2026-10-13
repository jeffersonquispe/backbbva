from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from src.application.ports.watchlist_port import Watchlist, WatchlistType
from src.application.use_cases.watchlists.add_watchlist_elements import (
    AddWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.add_watchlist_elements import (
    WatchlistNotFoundError as AddElementsWatchlistNotFoundError,
)
from src.application.use_cases.watchlists.check_watchlist_membership import (
    CheckWatchlistMembershipUseCase,
)
from src.application.use_cases.watchlists.create_watchlist import CreateWatchlistUseCase
from src.application.use_cases.watchlists.delete_watchlist import DeleteWatchlistUseCase
from src.application.use_cases.watchlists.get_watchlist import GetWatchlistUseCase
from src.application.use_cases.watchlists.list_watchlist_elements import (
    ListWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.list_watchlists import ListWatchlistsUseCase
from src.application.use_cases.watchlists.remove_watchlist_elements import (
    RemoveWatchlistElementsUseCase,
)
from src.application.use_cases.watchlists.update_watchlist import (
    UpdateWatchlistUseCase,
    WatchlistNotFoundError,
)
from src.infrastructure.entrypoint.api.factories.watchlist_factory import (
    get_add_watchlist_elements_use_case,
    get_check_watchlist_membership_use_case,
    get_create_watchlist_use_case,
    get_delete_watchlist_use_case,
    get_get_watchlist_use_case,
    get_list_watchlist_elements_use_case,
    get_list_watchlists_use_case,
    get_remove_watchlist_elements_use_case,
    get_update_watchlist_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    AddWatchlistElementsRequest,
    AddWatchlistElementsResponse,
    CheckWatchlistMembershipRequest,
    CheckWatchlistMembershipResponse,
    CreateWatchlistRequest,
    RemoveWatchlistElementsRequest,
    RemoveWatchlistElementsResponse,
    UpdateWatchlistRequest,
    WatchlistElementsPageSchema,
    WatchlistMatchSchema,
    WatchlistSchema,
)

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

# A "gigantic" list of short values (accounts, IPs, documents) at tens of
# thousands of rows is a few MB of text at most - generous ceiling, not a
# real limit. Bigger imports should be chunked client-side into several
# calls rather than raising this further.
MAX_IMPORT_BYTES = 10 * 1024 * 1024


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


@router.get("/{watchlist_id}", response_model=WatchlistSchema)
def get_watchlist(
    watchlist_id: str,
    use_case: Annotated[GetWatchlistUseCase, Depends(get_get_watchlist_use_case)],
):
    watchlist = use_case.execute(watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=404, detail=f"Watchlist not found: {watchlist_id}")
    return _to_schema(watchlist)


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


@router.get("/{watchlist_id}/elements", response_model=WatchlistElementsPageSchema)
def list_watchlist_elements(
    watchlist_id: str,
    use_case: Annotated[
        ListWatchlistElementsUseCase, Depends(get_list_watchlist_elements_use_case)
    ],
    limit: int = 100,
    cursor: str | None = None,
):
    page = use_case.execute(watchlist_id, limit=min(max(limit, 1), 500), cursor=cursor)
    return WatchlistElementsPageSchema(values=page.values, next_cursor=page.next_cursor)


@router.post("/{watchlist_id}/elements", response_model=AddWatchlistElementsResponse)
def add_watchlist_elements(
    watchlist_id: str,
    request: AddWatchlistElementsRequest,
    use_case: Annotated[
        AddWatchlistElementsUseCase, Depends(get_add_watchlist_elements_use_case)
    ],
):
    try:
        added = use_case.execute(watchlist_id, request.values)
    except AddElementsWatchlistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AddWatchlistElementsResponse(added=added)


@router.post("/{watchlist_id}/elements/import", response_model=AddWatchlistElementsResponse)
async def import_watchlist_elements(
    watchlist_id: str,
    use_case: Annotated[
        AddWatchlistElementsUseCase, Depends(get_add_watchlist_elements_use_case)
    ],
    file: UploadFile,
):
    if not file.filename or not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(status_code=400, detail="Only .csv or .txt files are supported")
    content = await file.read()
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    values = _parse_values_file(content)
    try:
        added = use_case.execute(watchlist_id, values)
    except AddElementsWatchlistNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AddWatchlistElementsResponse(added=added)


@router.delete("/{watchlist_id}/elements", response_model=RemoveWatchlistElementsResponse)
def remove_watchlist_elements(
    watchlist_id: str,
    request: RemoveWatchlistElementsRequest,
    use_case: Annotated[
        RemoveWatchlistElementsUseCase, Depends(get_remove_watchlist_elements_use_case)
    ],
):
    removed = use_case.execute(watchlist_id, request.values)
    return RemoveWatchlistElementsResponse(removed=removed)


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


def _parse_values_file(content: bytes) -> list[str]:
    # csv.reader handles both a bare newline-per-value .txt file (each row
    # ends up with one column) and a real exported .csv - first column of
    # every non-empty row is the value, extra columns are ignored.
    text = content.decode("utf-8-sig", errors="replace")
    return [
        row[0].strip()
        for row in csv.reader(io.StringIO(text))
        if row and row[0].strip()
    ]


def _to_schema(watchlist: Watchlist) -> WatchlistSchema:
    return WatchlistSchema(
        id=watchlist.id,
        name=watchlist.name,
        description=watchlist.description,
        list_type=watchlist.list_type,
        element_count=watchlist.element_count,
        active=watchlist.active,
        created_at=watchlist.created_at,
        updated_at=watchlist.updated_at,
    )
