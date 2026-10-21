from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.application.ports.local_auth_port import LocalUser
from src.application.use_cases.agent.draft_taxonomy import (
    ConfirmTaxonomyDraftInput,
    GenerateTaxonomyDraftInput,
    TaxonomyDraftConflictError,
    TaxonomyDraftNotFoundError,
    TaxonomyDraftPolicyError,
)
from src.infrastructure.agents.factories import get_agent_session_repository
from src.infrastructure.entrypoint.api.authorization import require_library_access
from src.infrastructure.entrypoint.api.factories.agent_taxonomy_draft_factory import (
    get_confirm_taxonomy_draft_use_case,
    get_generate_taxonomy_draft_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

router = APIRouter(prefix="/agent/sessions", tags=["agent-taxonomy-drafts"], dependencies=[Depends(require_library_access)])


class GenerateTaxonomyDraftRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    operation: str = Field(pattern="^(create|update)$")
    target_id: str | None = None


class ConfirmTaxonomyDraftRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=128)


@router.post("/{session_id}/taxonomy-drafts", status_code=201)
def generate_taxonomy_draft(session_id: str, request: GenerateTaxonomyDraftRequest, user: Annotated[LocalUser, Depends(get_current_user)]):
    try:
        package, checks = get_generate_taxonomy_draft_use_case().execute(GenerateTaxonomyDraftInput(
            session_id=session_id, owner_id=str(user.id), client_message_id=request.client_message_id,
            operation=request.operation, target_id=request.target_id))
    except TaxonomyDraftNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": "DRAFT_SOURCE_NOT_FOUND"}) from error
    except TaxonomyDraftPolicyError as error:
        raise HTTPException(status_code=409, detail={"code": "DRAFT_POLICY"}) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail={"code": "DRAFT_GENERATION_UNAVAILABLE"}) from error
    return {"package_id": package.package_id, "session_id": package.session_id, "status": package.status,
            "content_hash": package.content_hash, "content": package.content, "verifications": checks}


@router.get("/{session_id}/taxonomy-drafts/{package_id}")
def get_taxonomy_draft(session_id: str, package_id: str, user: Annotated[LocalUser, Depends(get_current_user)]):
    from src.infrastructure.agents.factories import (
        get_agent_package_repository,
        get_agent_verification_repository,
    )
    session = get_agent_session_repository().get(session_id)
    if session is None or session.owner_id != str(user.id):
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND"})
    package = get_agent_package_repository().get(package_id)
    if package is None or package.session_id != session_id:
        raise HTTPException(status_code=404, detail={"code": "DRAFT_NOT_FOUND"})
    return {"package_id": package.package_id, "session_id": package.session_id, "status": package.status,
            "content_hash": package.content_hash, "content": package.content,
            "verifications": get_agent_verification_repository().list_for_subject(package_id)}


@router.post("/{session_id}/taxonomy-drafts/{package_id}/confirm")
def confirm_taxonomy_draft(session_id: str, package_id: str, request: ConfirmTaxonomyDraftRequest, user: Annotated[LocalUser, Depends(get_current_user)]):
    try:
        return get_confirm_taxonomy_draft_use_case().execute(ConfirmTaxonomyDraftInput(
            session_id=session_id, owner_id=str(user.id), role=user.role.value,
            package_id=package_id, item_id=request.item_id))
    except TaxonomyDraftNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": "DRAFT_NOT_FOUND"}) from error
    except TaxonomyDraftConflictError as error:
        raise HTTPException(status_code=409, detail={"code": "DRAFT_STALE"}) from error
    except TaxonomyDraftPolicyError as error:
        raise HTTPException(status_code=409, detail={"code": "DRAFT_NOT_VERIFIED"}) from error
