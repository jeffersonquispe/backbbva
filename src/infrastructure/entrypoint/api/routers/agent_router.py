from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.agent.create_agent_session import (
    AgentPromptMissingError,
    AgentSessionPolicyError,
    CreateAgentSessionInput,
)
from src.application.use_cases.agent.manage_agent_session import (
    AgentSessionNotFoundError,
    AgentSessionStateError,
)
from src.infrastructure.agents.factories import (
    get_agent_package_repository,
    get_agent_session_repository,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.agent_factory import (
    get_assistant_optimizer_settings_port,
    get_create_agent_session_use_case,
    get_manage_agent_session_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas.agent import (
    AgentPackageSummaryResponse,
    AgentSessionResponse,
    CreateAgentSessionRequest,
)
from src.infrastructure.queues.celery.agent_dispatcher import (
    enqueue_agent_session_tick,
)

router = APIRouter(prefix="/agent", tags=["agent"])
_CONFIGURATION_ACCESS = Depends(require_permission("configuration"))


@router.post(
    "/sessions",
    response_model=AgentSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    request: CreateAgentSessionRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    settings=Depends(get_assistant_optimizer_settings_port),
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    if (
        request.mode == "optimization"
        and user.role != LocalRole.CHANNEL_MANAGER
    ):
        raise HTTPException(status_code=403, detail={"code": "ROLE_NOT_ALLOWED"})
    use_case = get_create_agent_session_use_case(settings)
    try:
        session = use_case.execute(
            CreateAgentSessionInput(
                owner_id=str(user.id),
                mode=request.mode,
                scope={"areas": request.scope},
                requested_budget=request.requested_budget,
            )
        )
    except AgentSessionPolicyError as error:
        raise HTTPException(status_code=409, detail={"code": "SESSION_POLICY"}) from error
    except AgentPromptMissingError as error:
        raise HTTPException(
            status_code=503, detail={"code": "AGENT_PROMPT_NOT_READY"}
        ) from error
    return session


@router.get("/sessions", response_model=list[AgentSessionResponse])
def list_sessions(
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    limit: int = 50,
):
    return get_agent_session_repository().list_by_owner(str(user.id), limit)


@router.get("/sessions/{session_id}", response_model=AgentSessionResponse)
def get_session(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    return _owned_session(session_id, str(user.id))


@router.post("/sessions/{session_id}/start", response_model=AgentSessionResponse)
def start_session(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    settings=Depends(get_assistant_optimizer_settings_port),
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    return _control_session("start", session_id, str(user.id), settings)


@router.post("/sessions/{session_id}/pause", response_model=AgentSessionResponse)
def pause_session(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    return _control_session("pause", session_id, str(user.id), None)


@router.post("/sessions/{session_id}/resume", response_model=AgentSessionResponse)
def resume_session(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    return _control_session("resume", session_id, str(user.id), None)


@router.post("/sessions/{session_id}/cancel", response_model=AgentSessionResponse)
def cancel_session(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    return _control_session("cancel", session_id, str(user.id), None)


@router.get(
    "/sessions/{session_id}/packages",
    response_model=list[AgentPackageSummaryResponse],
)
def list_session_packages(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    limit: int = 50,
):
    _owned_session(session_id, str(user.id))
    return get_agent_package_repository().list_for_session(session_id, limit)


@router.get("/packages/{package_id}", response_model=AgentPackageSummaryResponse)
def get_package(
    package_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    package = get_agent_package_repository().get(package_id)
    if package is None:
        raise HTTPException(status_code=404, detail={"code": "PACKAGE_NOT_FOUND"})
    _owned_session(package.session_id, str(user.id))
    return package


def _control_session(method: str, session_id: str, owner_id: str, settings):
    use_case = get_manage_agent_session_use_case(settings)
    try:
        session = getattr(use_case, method)(session_id, owner_id)
        if method in {"start", "resume"}:
            enqueue_agent_session_tick(session_id)
        return session
    except AgentSessionNotFoundError as error:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND"}) from error
    except AgentSessionStateError as error:
        raise HTTPException(status_code=409, detail={"code": "SESSION_STATE"}) from error


def _owned_session(session_id: str, owner_id: str):
    session = get_agent_session_repository().get(session_id)
    if session is None or session.owner_id != owner_id:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND"})
    return session
