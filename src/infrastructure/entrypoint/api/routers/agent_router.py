from __future__ import annotations

from typing import Annotated, Literal

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
from src.application.use_cases.agent.get_agent_session_overview import (
    AgentOverviewNotFoundError,
)
from src.application.use_cases.agent.manage_agent_insight import (
    AgentInsightNotFoundError,
    AgentInsightStateError,
)
from src.application.use_cases.agent.manage_agent_session import (
    AgentSessionNotFoundError,
    AgentSessionStateError,
)
from src.application.use_cases.agent.optimizer_memory import scope_key_for
from src.application.use_cases.agent.renew_agent_budget import (
    AgentBudgetRenewalError,
)
from src.application.use_cases.agent.resolve_agent_block import (
    AgentBlockNotFoundError,
    AgentBlockPolicyError,
    ResolveAgentBlockInput,
)
from src.domain.agents.failure_catalog import CATALOG
from src.domain.agents.finding import OptimizerInsightStatus
from src.domain.agents.optimization_run import experiment_stream_key
from src.infrastructure.agents.factories import (
    get_agent_audit_repository,
    get_agent_budget_ledger_repository,
    get_agent_event_repository,
    get_agent_experiment_repository,
    get_agent_finding_repository,
    get_agent_hypothesis_repository,
    get_agent_iteration_repository,
    get_agent_link_repository,
    get_agent_message_repository,
    get_agent_package_repository,
    get_agent_run_repository,
    get_agent_session_repository,
    get_agent_session_summary_repository,
    get_agent_tool_call_repository,
    get_optimization_run_repository,
    get_optimizer_insight_repository,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.agent_factory import (
    get_agent_chat_dispatcher,
    get_agent_entity_claim_use_case,
    get_agent_session_overview_use_case,
    get_assistant_optimizer_settings_port,
    get_chat_with_agent_use_case,
    get_create_agent_session_use_case,
    get_manage_agent_insight_use_case,
    get_manage_agent_session_use_case,
    get_optimizer_launch_limits_use_case,
    get_optimizer_status_use_case,
    get_renew_agent_budget_use_case,
    get_resolve_agent_block_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas.agent import (
    AgentAuditPageResponse,
    AgentChatTurnResponse,
    AgentEntityClaimResponse,
    AgentEventsPageResponse,
    AgentExperimentResponse,
    AgentFailureResponse,
    AgentFindingResponse,
    AgentHypothesisResponse,
    AgentInsightResponse,
    AgentLinkResponse,
    AgentMessageResponse,
    AgentPackageSummaryResponse,
    AgentSessionOverviewResponse,
    AgentSessionResponse,
    AgentSessionSummaryResponse,
    CreateAgentSessionRequest,
    OptimizationRunResponse,
    OptimizerInsightResponse,
    OptimizerLaunchLimitsResponse,
    OptimizerStatusResponse,
    RenewAgentBudgetRequest,
    ResolveAgentBlockRequest,
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
        raise HTTPException(
            status_code=409, detail={"code": "BUDGET_RENEWAL_POLICY"}
        ) from error


@router.get(
    "/sessions/{session_id}/overview", response_model=AgentSessionOverviewResponse
)
def get_session_overview(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    try:
        return get_agent_session_overview_use_case().execute(session_id, str(user.id))
    except AgentOverviewNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "SESSION_NOT_FOUND"}
        ) from error


@router.get("/sessions/{session_id}/events", response_model=AgentEventsPageResponse)
def list_session_events(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    after_seq: int = 0,
    limit: int = 100,
):
    _owned_session(session_id, str(user.id))
    if after_seq < 0 or limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PAGE"})
    items = get_agent_event_repository().list_for_session(
        session_id, after_seq=after_seq, limit=limit
    )
    return {"items": items, "last_seq": items[-1].seq if items else after_seq}


@router.get(
    "/sessions/{session_id}/findings", response_model=list[AgentFindingResponse]
)
def list_session_findings(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    _owned_session(session_id, str(user.id))
    return get_agent_finding_repository().list_for_session(session_id)


@router.get("/optimization-runs/{session_id}", response_model=OptimizationRunResponse)
def get_optimization_run(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    """Root, candidates with their conclusion, experiments and findings at once."""
    session = _owned_session(session_id, str(user.id))
    tree = get_optimization_run_repository().load_tree(session_id)
    if tree is None:
        # The run is created on the session's first tick; until then it is empty.
        return {
            "run_id": session_id,
            "status": "PENDING",
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "events_stream": session_id,
        }
    root = tree.root
    return {
        **{
            field: getattr(root, field)
            for field in (
                "run_id",
                "created_at",
                "updated_at",
                "objective_id",
                "objective_version",
                "baseline_components",
                "budget_limits",
                "optimizer_settings",
                "scope_areas",
                "insight_ids",
                "memory_insight_ids",
                "winners",
                "winning_components",
                "strategy",
                "events_stream",
            )
        },
        "status": root.status.value,
        "candidates": [
            {
                "hypothesis": {
                    **vars(candidate.hypothesis),
                    "status": candidate.hypothesis.status.value,
                },
                "experiments": [
                    {**vars(view.experiment), "events_stream": view.events_stream}
                    for view in candidate.experiments
                ],
            }
            for candidate in tree.candidates
        ],
        "findings": list(tree.findings),
    }


@router.get(
    "/sessions/{session_id}/experiments/{experiment_id}/events",
    response_model=AgentEventsPageResponse,
)
def list_experiment_events(
    session_id: str,
    experiment_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    after_seq: int = 0,
    limit: int = 100,
):
    """The experiment's own timeline, separate from the session's."""
    _owned_session(session_id, str(user.id))
    if after_seq < 0 or limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PAGE"})
    items = get_agent_event_repository().list_for_session(
        experiment_stream_key(session_id, experiment_id),
        after_seq=after_seq,
        limit=limit,
    )
    return {"items": items, "last_seq": items[-1].seq if items else after_seq}


@router.get("/sessions/{session_id}/runs/{run_id}/tool-calls")
def list_run_tool_calls(
    session_id: str,
    run_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
) -> list[dict[str, object]]:
    """Measured calls of one specialist run (duration, cost, safe result only)."""
    _owned_session(session_id, str(user.id))
    run = get_agent_run_repository().get(run_id)
    if run is None or run.session_id != session_id:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND"})
    return [
        {
            "call_id": call.call_id,
            "tool_name": call.tool_name,
            "status": call.status,
            "safe_result_summary": call.safe_result_summary or {},
            "created_at": call.created_at.isoformat(),
        }
        for call in get_agent_tool_call_repository().list_for_run(run_id)
    ]


@router.get("/optimizer-launch-limits", response_model=OptimizerLaunchLimitsResponse)
def get_optimizer_launch_limits(
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    """Enablement, concurrency and per-session budget ceiling shown before launching."""
    return get_optimizer_launch_limits_use_case().execute()


@router.get(
    "/optimizer-status",
    response_model=OptimizerStatusResponse,
    dependencies=[Depends(require_permission("monitor"))],
)
def get_optimizer_status():
    """Current optimizer load for the Monitor: counts and caps, never ids."""
    return get_optimizer_status_use_case().execute()


@router.get("/failure-catalog", response_model=list[AgentFailureResponse])
def list_failure_catalog(
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    """Spanish explanation, retry hint and required approval for every code."""
    return list(CATALOG.values())


@router.get("/memory", response_model=list[OptimizerInsightResponse])
def list_optimizer_memory(
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    area: Literal["configuration", "library", "vector_store", "model"] = "model",
):
    """Supported, data-backed learnings from earlier optimizer sessions."""
    return get_optimizer_insight_repository().list_by_scope(
        scope_key_for(area), OptimizerInsightStatus.SUPPORTED, 20
    )


@router.post(
    "/sessions/{session_id}/block/resolve", response_model=AgentSessionResponse
)
def resolve_session_block(
    session_id: str,
    request: ResolveAgentBlockRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    if user.role != LocalRole.CHANNEL_MANAGER:
        raise HTTPException(status_code=403, detail={"code": "ROLE_NOT_ALLOWED"})
    try:
        session = get_resolve_agent_block_use_case().execute(
            ResolveAgentBlockInput(
                session_id=session_id,
                actor_id=str(user.id),
                kind=request.kind,
                additions=request.additions,
                allowance=request.allowance,
                note=request.note,
            )
        )
    except AgentBlockNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "SESSION_NOT_FOUND"}
        ) from error
    except AgentBlockPolicyError as error:
        raise HTTPException(status_code=409, detail={"code": error.code}) from error
    enqueue_agent_session_tick(session.session_id)
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


@router.get(
    "/sessions/{session_id}/audit",
    response_model=AgentAuditPageResponse,
)
def list_session_audit(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    limit: int = 50,
    cursor: str | None = None,
):
    _owned_session(session_id, str(user.id))
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PAGE_SIZE"})
    try:
        items, next_cursor = get_agent_audit_repository().list_for_session(
            session_id, cursor=cursor, limit=limit
        )
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_AUDIT_CURSOR"}
        ) from error
    return {"items": items, "next_cursor": next_cursor}


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


@router.get(
    "/sessions/{session_id}/experiments",
    response_model=list[AgentExperimentResponse],
)
def list_session_experiments(
    session_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
    limit: int = 50,
):
    _owned_session(session_id, str(user.id))
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PAGE"})
    return get_agent_experiment_repository().list_for_session(session_id, limit)


@router.get(
    "/sessions/{session_id}/experiments/{experiment_id}",
    response_model=AgentExperimentResponse,
)
def get_session_experiment(
    session_id: str,
    experiment_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    _owned_session(session_id, str(user.id))
    experiment = get_agent_experiment_repository().get(session_id, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail={"code": "EXPERIMENT_NOT_FOUND"})
    return experiment


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
            "hypothesis_id": item.decision.get("hypothesis_id"),
            "objective_id": item.decision.get("objective_id"),
            "objective_version": item.decision.get("objective_version"),
            "specialist": item.decision.get("specialist"),
            "verification_status": item.decision.get("verification_status"),
            "specialist_verified": item.decision.get("specialist_verified", False),
            "failure_stage": item.decision.get("failure_stage"),
            "failure_code": item.decision.get("failure_code"),
            "experiment_verified": item.decision.get("experiment_verified", False),
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


@router.post(
    "/sessions/{session_id}/messages",
    response_model=AgentChatTurnResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def send_message(
    session_id: str,
    request: SendAgentMessageRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    _: LocalUser = _CONFIGURATION_ACCESS,
):
    """Store the turn and queue the reply; the client polls ``GET .../messages``.

    A retry with the same ``client_message_id`` returns the stored turn, and
    queues the reply again only if the assistant has not answered yet.
    """
    role = str(getattr(user.role, "value", user.role))
    try:
        turn = get_chat_with_agent_use_case().accept(
            ChatWithAgentInput(
                session_id=session_id,
                owner_id=str(user.id),
                client_message_id=request.client_message_id,
                content=request.content,
                page_path=request.page_path,
                role=role,
            )
        )
        if turn.assistant_message is None:
            get_agent_chat_dispatcher().dispatch(
                session_id=session_id,
                owner_id=str(user.id),
                client_message_id=request.client_message_id,
                page_path=request.page_path[:200],
                role=role,
            )
        return turn
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
