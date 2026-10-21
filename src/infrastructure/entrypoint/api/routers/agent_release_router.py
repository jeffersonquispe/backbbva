from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.application.ports.agent_release_port import AgentReleaseRepository
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.agent.manage_agent_release import (
    AgentReleasePolicyError,
    ManageAgentReleaseUseCase,
)
from src.application.use_cases.agent.validate_retrospective_release import (
    RetrospectiveValidationError,
    RetrospectiveValidationInput,
    ValidateRetrospectiveReleaseUseCase,
)
from src.domain.agents.release import AgentRelease, RetrospectiveValidation
from src.infrastructure.entrypoint.api.factories.agent_release_factory import (
    get_agent_release_repository,
    get_manage_agent_release_use_case,
    get_validate_retrospective_release_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

router = APIRouter(prefix="/agent/releases", tags=["agent releases"])


class RetrospectiveValidationRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    experiment_id: str = Field(min_length=1, max_length=100)


class ReleaseRequest(BaseModel):
    validation_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=10, max_length=1000)


class ReleaseTransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=1000)


class AdvanceReleaseRequest(ReleaseTransitionRequest):
    target_stage: str


class ComponentPinResponse(BaseModel):
    component: str
    entity_id: str
    version: str
    content_sha256: str


class RetrospectiveValidationResponse(BaseModel):
    validation_id: str
    session_id: str
    experiment_id: str
    status: str
    snapshot_id: str
    snapshot_sha256: str
    component_pins: list[ComponentPinResponse]
    baseline_component_pins: list[ComponentPinResponse]
    evidence: dict[str, Any]
    created_by: str
    created_by_id: str
    created_at: str
    error_code: str | None = None


class AgentReleaseResponse(BaseModel):
    release_id: str
    validation_id: str
    session_id: str
    experiment_id: str
    status: str
    candidate_component_pins: list[ComponentPinResponse]
    previous_component_pins: list[ComponentPinResponse]
    requested_by: str
    requested_by_id: str
    requested_at: str
    title: str
    reason: str
    snapshot_id: str
    snapshot_sha256: str
    rollout_policy_version: str
    version: int
    approved_by: str | None = None
    approved_by_id: str | None = None
    approved_at: str | None = None
    updated_at: str | None = None
    observations: dict[str, Any]
    rollback_reason: str | None = None


def _require_role(user: LocalUser, *roles: LocalRole) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="ROLE_NOT_PERMITTED")


def _validation_response(value: RetrospectiveValidation) -> dict[str, Any]:
    return {
        **asdict(value),
        "status": value.status.value,
        "component_pins": [asdict(pin) for pin in value.component_pins],
        "baseline_component_pins": [
            asdict(pin) for pin in value.baseline_component_pins
        ],
        "created_at": value.created_at.isoformat(),
    }


def _release_response(value: AgentRelease) -> dict[str, Any]:
    return {
        **asdict(value),
        "status": value.status.value,
        "candidate_component_pins": [
            asdict(pin) for pin in value.candidate_component_pins
        ],
        "previous_component_pins": [
            asdict(pin) for pin in value.previous_component_pins
        ],
        "requested_at": value.requested_at.isoformat(),
        "approved_at": value.approved_at.isoformat() if value.approved_at else None,
        "updated_at": value.updated_at.isoformat() if value.updated_at else None,
    }


@router.post(
    "/retrospective-validations",
    response_model=RetrospectiveValidationResponse,
    status_code=status.HTTP_201_CREATED,
)
def validate_retrospective(
    request: RetrospectiveValidationRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        ValidateRetrospectiveReleaseUseCase,
        Depends(get_validate_retrospective_release_use_case),
    ],
):
    _require_role(
        user, LocalRole.CHANNEL_MANAGER, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER
    )
    try:
        result = use_case.execute(
            RetrospectiveValidationInput(
                session_id=request.session_id,
                experiment_id=request.experiment_id,
                actor=user.name,
                actor_id=str(user.id),
            )
        )
    except RetrospectiveValidationError as error:
        code = str(error)
        raise HTTPException(
            status_code=404 if code == "EXPERIMENT_NOT_FOUND" else 422,
            detail=code,
        ) from error
    return _validation_response(result)


@router.get(
    "/retrospective-validations/{validation_id}",
    response_model=RetrospectiveValidationResponse,
)
def get_retrospective_validation(
    validation_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    repository: Annotated[AgentReleaseRepository, Depends(get_agent_release_repository)],
):
    _require_role(user, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER)
    result = repository.get_validation(validation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="VALIDATION_NOT_FOUND")
    return _validation_response(result)


@router.post("", response_model=AgentReleaseResponse, status_code=201)
def request_release(
    request: ReleaseRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        ManageAgentReleaseUseCase, Depends(get_manage_agent_release_use_case)
    ],
):
    _require_role(user, LocalRole.CHANNEL_MANAGER)
    try:
        result = use_case.request(
            validation_id=request.validation_id,
            title=request.title,
            reason=request.reason,
            actor=user.name,
            actor_id=str(user.id),
        )
    except AgentReleasePolicyError as error:
        code = str(error)
        raise HTTPException(
            status_code=404 if code == "VALIDATION_NOT_FOUND" else 409,
            detail=code,
        ) from error
    return _release_response(result)


@router.get("", response_model=list[AgentReleaseResponse])
def list_releases(
    user: Annotated[LocalUser, Depends(get_current_user)],
    repository: Annotated[AgentReleaseRepository, Depends(get_agent_release_repository)],
):
    _require_role(user, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER)
    return [
        _release_response(item)
        for item in repository.list_releases()
    ]


@router.get("/{release_id}", response_model=AgentReleaseResponse)
def get_release(
    release_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    repository: Annotated[
        AgentReleaseRepository, Depends(get_agent_release_repository)
    ],
):
    _require_role(user, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER)
    result = repository.get_release(release_id)
    if result is None:
        raise HTTPException(status_code=404, detail="RELEASE_NOT_FOUND")
    return _release_response(result)


@router.post("/{release_id}/submit", response_model=AgentReleaseResponse)
def submit_release_for_approval(
    release_id: str,
    request: ReleaseTransitionRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        ManageAgentReleaseUseCase, Depends(get_manage_agent_release_use_case)
    ],
):
    _require_role(user, LocalRole.CHANNEL_MANAGER)
    return _transition(
        lambda: use_case.submit_for_approval(
            release_id,
            expected_version=request.expected_version,
            actor=user.name,
            actor_id=str(user.id),
            reason=request.reason,
        )
    )


@router.post("/{release_id}/approve", response_model=AgentReleaseResponse)
def approve_release(
    release_id: str,
    request: ReleaseTransitionRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        ManageAgentReleaseUseCase, Depends(get_manage_agent_release_use_case)
    ],
):
    _require_role(user, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER)
    return _transition(
        lambda: use_case.approve(
            release_id,
            expected_version=request.expected_version,
            actor=user.name,
            actor_id=str(user.id),
            reason=request.reason,
        )
    )


@router.post("/{release_id}/advance", response_model=AgentReleaseResponse)
def advance_release(
    release_id: str,
    request: AdvanceReleaseRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        ManageAgentReleaseUseCase, Depends(get_manage_agent_release_use_case)
    ],
):
    _require_role(user, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER)
    return _transition(
        lambda: use_case.advance(
            release_id,
            expected_version=request.expected_version,
            actor=user.name,
            actor_id=str(user.id),
            target_stage=request.target_stage,
            reason=request.reason,
        )
    )


@router.post("/{release_id}/rollback", response_model=AgentReleaseResponse)
def rollback_release(
    release_id: str,
    request: ReleaseTransitionRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        ManageAgentReleaseUseCase, Depends(get_manage_agent_release_use_case)
    ],
):
    _require_role(user, LocalRole.MANAGER, LocalRole.RELEASE_MANAGER)
    return _transition(
        lambda: use_case.rollback(
            release_id,
            expected_version=request.expected_version,
            actor=user.name,
            actor_id=str(user.id),
            reason=request.reason,
        )
    )


def _transition(callback):
    try:
        return _release_response(callback())
    except AgentReleasePolicyError as error:
        code = str(error)
        raise HTTPException(
            status_code=404 if code == "RELEASE_NOT_FOUND" else 409,
            detail=code,
        ) from error
    except ValueError as error:
        code = str(error)
        raise HTTPException(status_code=409, detail=code) from error
