from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.agent.chat_with_agent import (
    AgentChatNotFoundError,
    AgentChatPolicyError,
    AgentMessageLimitError,
    AgentMessageTooLongError,
    ChatWithAgentInput,
)
from src.application.use_cases.agent.create_agent_session import (
    AgentPromptMissingError,
    AgentSessionPolicyError,
    CreateAgentSessionInput,
)
from src.application.use_cases.agent.manage_agent_insight import (
    AgentInsightNotFoundError,
    AgentInsightStateError,
)
from src.application.use_cases.agent.manage_agent_session import (
    AgentSessionNotFoundError,
    AgentSessionStateError,
)
from src.application.use_cases.agent.renew_agent_budget import (
    AgentBudgetRenewalError,
)
from src.infrastructure.agents.factories import (
    get_agent_budget_ledger_repository,
    get_agent_hypothesis_repository,
    get_agent_iteration_repository,
    get_agent_link_repository,
    get_agent_message_repository,
    get_agent_package_repository,
    get_agent_run_repository,
    get_agent_session_repository,
    get_agent_session_summary_repository,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.agent_factory import (
    get_agent_entity_claim_use_case,
    get_assistant_optimizer_settings_port,
    get_chat_with_agent_use_case,
    get_create_agent_session_use_case,
    get_manage_agent_insight_use_case,
    get_manage_agent_session_use_case,
    get_renew_agent_budget_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas.agent import (
    AgentChatTurnResponse,
    AgentEntityClaimResponse,
    AgentHypothesisResponse,
    AgentInsightResponse,
    AgentLinkResponse,
    AgentMessageResponse,
    AgentPackageSummaryResponse,
    AgentSessionResponse,
    AgentSessionSummaryResponse,
    CreateAgentSessionRequest,
    RenewAgentBudgetRequest,
    SendAgentMessageRequest,
)
from src.infrastructure.queues.celery.agent_dispatcher import (
    enqueue_agent_session_tick,
)

router = APIRouter(prefix="/agent", tags=["agent"])
_CONFIGURATION_ACCESS = Depends(require_permission("configuration"))


@router.get("/claims/{entity_key:path}", response_model=list[AgentEntityClaimResponse])
def list_entity_claims(
    entity_key: str,
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    if not entity_key or len(entity_key) > 256:
        raise HTTPException(status_code=422, detail={"code": "INVALID_ENTITY_KEY"})
    return get_agent_entity_claim_use_case().list_active(entity_key)


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
    if request.mode == "optimization" and user.role != LocalRole.CHANNEL_MANAGER:
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
        raise HTTPException(
            status_code=409, detail={"code": "SESSION_POLICY"}
        ) from error
    except AgentPromptMissingError as error:
        raise HTTPException(
            status_code=503, detail={"code": "AGENT_PROMPT_NOT_READY"}
        ) from error
    return session


@router.post("/sessions/{session_id}/budget/renew", response_model=AgentSessionResponse)
def renew_budget(
    session_id: str,
    request: RenewAgentBudgetRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    if user.role != LocalRole.CHANNEL_MANAGER:
        raise HTTPException(status_code=403, detail={"code": "ROLE_NOT_ALLOWED"})
    try:
        return get_renew_agent_budget_use_case().execute(
            session_id, str(user.id), request.additions
        )
    except AgentBudgetRenewalError as error:
        raise HTTPException(status_code=409, detail={"code": "BUDGET_RENEWAL_POLICY"}) from error


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


@router.get(
    "/sessions/{session_id}/hypotheses",
    response_model=list[AgentHypothesisResponse],
)
def list_session_hypotheses(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    _owned_session(session_id, str(user.id))
    return get_agent_hypothesis_repository().list_for_session(session_id)


@router.get("/sessions/{session_id}/iterations")
def list_session_iterations(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    _owned_session(session_id, str(user.id))
    runs = get_agent_run_repository()
    return [
        {
            "number": item.number,
            "status": item.status.value,
            "started_at": item.started_at,
            "finished_at": item.finished_at,
            "hypothesis": item.decision.get("hypothesis"),
            "decision": item.decision.get("action"),
            "reason": item.decision.get("reason"),
            "specialists": sorted(
                {
                    run.subagent
                    for run_id in item.run_ids
                    if (run := runs.get(run_id)) is not None
                }
            ),
        }
        for item in get_agent_iteration_repository().list_for_session(session_id)
    ]


@router.get("/sessions/{session_id}/budget")
def get_session_budget(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    session = _owned_session(session_id, str(user.id))
    spent: dict[str, int] = {}
    for entry in get_agent_budget_ledger_repository().list_for_session(session_id):
        if entry.entry_type == "SPEND":
            spent[entry.resource] = spent.get(entry.resource, 0) + entry.amount
    return {
        "session_id": session_id,
        "spent": spent,
        "limits": session.budget_limits,
    }


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


@router.post("/sessions/{session_id}/messages", response_model=AgentChatTurnResponse)
def send_message(
    session_id: str,
    request: SendAgentMessageRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    try:
        return get_chat_with_agent_use_case().execute(
            ChatWithAgentInput(
                session_id=session_id,
                owner_id=str(user.id),
                client_message_id=request.client_message_id,
                content=request.content,
            )
        )
    except AgentChatNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "SESSION_NOT_FOUND"}
        ) from error
    except AgentMessageTooLongError as error:
        raise HTTPException(
            status_code=413, detail={"code": "MESSAGE_TOO_LONG"}
        ) from error
    except AgentMessageLimitError as error:
        raise HTTPException(
            status_code=409, detail={"code": "MESSAGE_LIMIT"}
        ) from error
    except AgentChatPolicyError as error:
        raise HTTPException(status_code=409, detail={"code": "CHAT_POLICY"}) from error
    except Exception as error:
        # Provider errors can contain request data; return only a safe code.
        raise HTTPException(
            status_code=503, detail={"code": "CHAT_UNAVAILABLE"}
        ) from error


@router.get(
    "/sessions/{session_id}/messages", response_model=list[AgentMessageResponse]
)
def list_messages(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    after_seq: int = 0,
    limit: int = 50,
):
    _owned_session(session_id, str(user.id))
    if after_seq < 0 or not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PAGE"})
    return get_agent_message_repository().list_after_seq(session_id, after_seq, limit)


@router.get(
    "/sessions/{session_id}/insights", response_model=list[AgentInsightResponse]
)
def list_insights(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    try:
        return get_manage_agent_insight_use_case().list_for_owner(
            session_id, str(user.id)
        )
    except AgentInsightNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "SESSION_NOT_FOUND"}
        ) from error


@router.post(
    "/sessions/{session_id}/insights/{insight_id}/confirm",
    response_model=AgentInsightResponse,
)
def confirm_insight(
    session_id: str,
    insight_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    return _change_insight("confirm", session_id, insight_id, str(user.id))


@router.post(
    "/sessions/{session_id}/insights/{insight_id}/reject",
    response_model=AgentInsightResponse,
)
def reject_insight(
    session_id: str,
    insight_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    return _change_insight("reject", session_id, insight_id, str(user.id))


@router.get("/sessions/{session_id}/links", response_model=list[AgentLinkResponse])
def list_links(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    source_type: str = "message",
    source_id: str = "",
):
    _owned_session(session_id, str(user.id))
    if not source_id:
        raise HTTPException(status_code=422, detail={"code": "SOURCE_REQUIRED"})
    return get_agent_link_repository().list_from(session_id, source_type, source_id)


@router.get(
    "/sessions/{session_id}/summary",
    response_model=AgentSessionSummaryResponse | None,
)
def get_session_summary(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    _owned_session(session_id, str(user.id))
    return get_agent_session_summary_repository().get_latest(session_id)


def _change_insight(method: str, session_id: str, insight_id: str, owner_id: str):
    try:
        return getattr(get_manage_agent_insight_use_case(), method)(
            session_id, insight_id, owner_id
        )
    except AgentInsightNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "INSIGHT_NOT_FOUND"}
        ) from error
    except AgentInsightStateError as error:
        raise HTTPException(
            status_code=409, detail={"code": "INSIGHT_STATE"}
        ) from error


def _control_session(method: str, session_id: str, owner_id: str, settings):
    use_case = get_manage_agent_session_use_case(settings)
    try:
        session = getattr(use_case, method)(session_id, owner_id)
        if method in {"start", "resume"}:
            enqueue_agent_session_tick(session_id)
        return session
    except AgentSessionNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "SESSION_NOT_FOUND"}
        ) from error
    except AgentSessionStateError as error:
        raise HTTPException(
            status_code=409, detail={"code": "SESSION_STATE"}
        ) from error


def _owned_session(session_id: str, owner_id: str):
    session = get_agent_session_repository().get(session_id)
    if session is None or session.owner_id != owner_id:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND"})
    return session
