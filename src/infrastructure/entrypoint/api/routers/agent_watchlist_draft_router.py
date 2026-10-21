from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.application.ports.local_auth_port import LocalUser
from src.application.use_cases.agent.draft_watchlist import (
    ConfirmWatchlistDraftInput,
    GenerateWatchlistDraftInput,
    WatchlistDraftConflictError,
    WatchlistDraftNotFoundError,
    WatchlistDraftPolicyError,
)
from src.infrastructure.agents.factories import (
    get_agent_package_repository,
    get_agent_session_repository,
    get_agent_verification_repository,
)
from src.infrastructure.entrypoint.api.authorization import require_library_access
from src.infrastructure.entrypoint.api.factories.agent_watchlist_draft_factory import (
    get_confirm_watchlist_draft_use_case,
    get_generate_watchlist_draft_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

router = APIRouter(
    prefix="/agent/sessions",
    tags=["agent-watchlist-drafts"],
    dependencies=[Depends(require_library_access)],
)


class GenerateWatchlistDraftRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    operation: str = Field(pattern="^(create|update)$")
    target_id: str | None = None


class ConfirmWatchlistDraftRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=128)


@router.post("/{session_id}/watchlist-drafts", status_code=201)
def generate_watchlist_draft(
    session_id: str,
    request: GenerateWatchlistDraftRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    try:
        result = get_generate_watchlist_draft_use_case().execute(
            GenerateWatchlistDraftInput(
                session_id=session_id,
                owner_id=str(user.id),
                client_message_id=request.client_message_id,
                operation=request.operation,
                target_id=request.target_id,
            )
        )
    except WatchlistDraftNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DRAFT_SOURCE_NOT_FOUND"}
        ) from error
    except WatchlistDraftPolicyError as error:
        raise HTTPException(status_code=409, detail={"code": "DRAFT_POLICY"}) from error
    except Exception as error:
        raise HTTPException(
            status_code=503, detail={"code": "DRAFT_GENERATION_UNAVAILABLE"}
        ) from error
    return _response(result.package, result.verifications)


@router.get("/{session_id}/watchlist-drafts/{package_id}")
def get_watchlist_draft(
    session_id: str,
    package_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _owned_session(session_id, str(user.id))
    package = get_agent_package_repository().get(package_id)
    if package is None or package.session_id != session_id:
        raise HTTPException(status_code=404, detail={"code": "DRAFT_NOT_FOUND"})
    return _response(
        package, get_agent_verification_repository().list_for_subject(package_id)
    )


@router.post("/{session_id}/watchlist-drafts/{package_id}/confirm")
def confirm_watchlist_draft(
    session_id: str,
    package_id: str,
    request: ConfirmWatchlistDraftRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    try:
        return get_confirm_watchlist_draft_use_case().execute(
            ConfirmWatchlistDraftInput(
                session_id=session_id,
                owner_id=str(user.id),
                role=user.role.value,
                package_id=package_id,
                item_id=request.item_id,
            )
        )
    except WatchlistDraftNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "DRAFT_NOT_FOUND"}
        ) from error
    except WatchlistDraftConflictError as error:
        raise HTTPException(status_code=409, detail={"code": "DRAFT_STALE"}) from error
    except WatchlistDraftPolicyError as error:
        raise HTTPException(
            status_code=409, detail={"code": "DRAFT_NOT_VERIFIED"}
        ) from error


def _owned_session(session_id: str, owner_id: str) -> None:
    session = get_agent_session_repository().get(session_id)
    if session is None or session.owner_id != owner_id:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND"})


def _response(package, verifications):
    return {
        "package_id": package.package_id,
        "session_id": package.session_id,
        "status": package.status,
        "content": package.content,
        "content_hash": package.content_hash,
        "verifications": verifications,
    }
