from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.local_auth_port import LocalUser
from src.application.use_cases.agent.draft_modus_operandi import (
    AgentDraftConflictError,
    AgentDraftGenerationUnavailableError,
    AgentDraftNotFoundError,
    AgentDraftPolicyError,
    ConfirmModusOperandiDraftInput,
    GenerateModusOperandiDraftInput,
)
from src.infrastructure.agents.factories import (
    get_agent_confirmation_repository,
    get_agent_package_repository,
    get_agent_session_repository,
    get_agent_verification_repository,
)
from src.infrastructure.entrypoint.api.authorization import require_library_access
from src.infrastructure.entrypoint.api.factories.agent_modus_operandi_draft_factory import (
    get_confirm_modus_operandi_draft_use_case,
    get_generate_modus_operandi_draft_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas.agent import (
    AgentConfirmationResponse,
    AgentDraftPackageResponse,
    ConfirmAgentDraftRequest,
    ConfirmAgentDraftResponse,
    GenerateModusOperandiDraftRequest,
)

router = APIRouter(
    prefix="/agent/sessions",
    tags=["agent-drafts"],
    dependencies=[Depends(require_library_access)],
)


@router.post(
    "/{session_id}/modus-operandi-drafts",
    response_model=AgentDraftPackageResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_modus_operandi_draft(
    session_id: str,
    request: GenerateModusOperandiDraftRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    try:
        result = get_generate_modus_operandi_draft_use_case().execute(
            GenerateModusOperandiDraftInput(
                session_id=session_id,
                owner_id=str(user.id),
                client_message_id=request.client_message_id,
                operation=request.operation,
                target_id=request.target_id,
            )
        )
    except AgentDraftNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": "DRAFT_SOURCE_NOT_FOUND"}) from error
    except AgentDraftPolicyError as error:
        raise HTTPException(status_code=409, detail={"code": "DRAFT_POLICY"}) from error
    except AgentDraftGenerationUnavailableError as error:
        raise HTTPException(
            status_code=503, detail={"code": "DRAFT_GENERATION_UNAVAILABLE"}
        ) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail={"code": "DRAFT_GENERATION_UNAVAILABLE"}) from error
    return _package_response(result.package, result.verifications)


@router.get(
    "/{session_id}/modus-operandi-drafts/{package_id}",
    response_model=AgentDraftPackageResponse,
)
def get_modus_operandi_draft(
    session_id: str,
    package_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _owned_session(session_id, str(user.id))
    package = get_agent_package_repository().get(package_id)
    if package is None or package.session_id != session_id:
        raise HTTPException(status_code=404, detail={"code": "DRAFT_NOT_FOUND"})
    verifications = get_agent_verification_repository().list_for_subject(package_id)
    return _package_response(package, verifications)


@router.post(
    "/{session_id}/modus-operandi-drafts/{package_id}/confirm",
    response_model=ConfirmAgentDraftResponse,
)
def confirm_modus_operandi_draft(
    session_id: str,
    package_id: str,
    request: ConfirmAgentDraftRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    try:
        result = get_confirm_modus_operandi_draft_use_case().execute(
            ConfirmModusOperandiDraftInput(
                session_id=session_id,
                owner_id=str(user.id),
                role=user.role.value,
                package_id=package_id,
                item_id=request.item_id,
            )
        )
    except AgentDraftNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": "DRAFT_NOT_FOUND"}) from error
    except AgentDraftConflictError as error:
        raise HTTPException(status_code=409, detail={"code": "DRAFT_STALE"}) from error
    except AgentDraftPolicyError as error:
        raise HTTPException(status_code=409, detail={"code": "DRAFT_NOT_VERIFIED"}) from error
    return result


@router.get(
    "/{session_id}/confirmations",
    response_model=list[AgentConfirmationResponse],
)
def list_session_confirmations(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _owned_session(session_id, str(user.id))
    return get_agent_confirmation_repository().list_for_session(session_id)


def _owned_session(session_id: str, owner_id: str):
    session = get_agent_session_repository().get(session_id)
    if session is None or session.owner_id != owner_id:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND"})
    return session


def _package_response(package, verifications):
    return {
        "package_id": package.package_id,
        "session_id": package.session_id,
        "status": package.status,
        "content_hash": package.content_hash,
        "content": package.content,
        "verifications": verifications,
    }
