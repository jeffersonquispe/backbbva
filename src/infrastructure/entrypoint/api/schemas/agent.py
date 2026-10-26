from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateAgentSessionRequest(BaseModel):
    mode: Literal["assistant", "optimization"]
    scope: list[Literal["library", "configuration", "vector_store", "model"]] = Field(
        default_factory=list
    )
    requested_budget: dict[str, int] = Field(default_factory=dict)


class RenewAgentBudgetRequest(BaseModel):
    additions: dict[str, int]


class AgentLeaseResponse(BaseModel):
    status: Literal["NONE", "ACTIVE", "EXPIRED"] = "NONE"
    expires_at: datetime | None = None
    heartbeat_at: datetime | None = None


class AgentAuditEventResponse(BaseModel):
    event_id: str
    occurred_at: datetime
    category: Literal[
        "session", "iteration", "specialist", "tool", "experiment", "lease", "release"
    ]
    status: str = Field(min_length=1, max_length=64)
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,64}$")
    duration_ms: int | None = Field(default=None, ge=0)
    cost_micros: int | None = Field(default=None, ge=0)
    specialist: (
        Literal[
            "optimizer",
            "configuration",
            "library",
            "vector_store",
            "model",
            "dataset",
            "xgboost",
        ]
        | None
    ) = None
    tool: (
        Literal[
            "read",
            "write",
            "evaluate",
            "search",
            "score",
            "persist",
            "dispatch",
            "configuration",
            "library",
            "vector_store",
            "xgboost",
        ]
        | None
    ) = None
    actor: str | None = None
    actor_id: str | None = None
    entity_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    snapshot_id: str | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    policy_version: str | None = None
    reason: str | None = Field(default=None, max_length=1000)


class AgentAuditPageResponse(BaseModel):
    items: list[AgentAuditEventResponse]
    next_cursor: str | None


class AgentSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime
    scope: dict[str, object] = Field(default_factory=dict)
    objective_id: str | None = None
    objective_version: int | None = None
    budget_limits: dict[str, int]
    prompt_versions: dict[str, dict[str, str]]
    rev: int
    budget_renewals: int = 0
    candidate_allowance: int = 0
    block: dict[str, object] = Field(default_factory=dict)
    lease: AgentLeaseResponse = Field(default_factory=AgentLeaseResponse)

    @model_validator(mode="before")
    @classmethod
    def derive_lease_view(cls, value):
        owner = (
            value.get("lease_owner")
            if isinstance(value, dict)
            else getattr(value, "lease_owner", None)
        )
        expires_at = (
            value.get("lease_expires_at")
            if isinstance(value, dict)
            else getattr(value, "lease_expires_at", None)
        )
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            state = "ACTIVE" if expires_at > datetime.now(UTC) else "EXPIRED"
        else:
            state = "ACTIVE" if owner else "NONE"
        lease = {
            "status": state,
            "expires_at": expires_at,
            "heartbeat_at": None,
        }
        if isinstance(value, dict):
            return {**value, "lease": lease}
        return {**value.__dict__, "lease": lease}


class AgentPackageSummaryResponse(BaseModel):
    package_id: str
    session_id: str
    iteration_number: int
    status: str
    content_hash: str | None
    created_at: datetime | None
    sealed_at: datetime | None


class SendAgentMessageRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1)
    page_path: str = Field(default="", max_length=200)


class AgentMessageReferenceResponse(BaseModel):
    id: str
    kind: str
    label: str
    path: str = ""


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: str
    client_message_id: str
    seq: int
    role: str
    content: str
    created_at: datetime
    redaction_counts: dict[str, int]
    extracted_insight_ids: tuple[str, ...] = ()
    references: list[AgentMessageReferenceResponse] = Field(default_factory=list)
    context_used: list[AgentMessageReferenceResponse] = Field(default_factory=list)


class AgentChatTurnResponse(BaseModel):
    user_message: AgentMessageResponse
    assistant_message: AgentMessageResponse | None
    proposed_insights: list[AgentInsightResponse] = Field(default_factory=list)


class AgentInsightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    insight_id: str
    kind: str
    statement: str
    scope: dict[str, str]
    status: str
    proposed_by: str
    source_message_id: str | None
    created_at: datetime
    confidence: float | None


class AgentLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_type: str
    source_id: str
    relation: str
    target_type: str
    target_id: str
    created_at: datetime


class AgentSessionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    version: int
    content: dict[str, object]
    covers_seq_from: int
    covers_seq_to: int
    created_at: datetime


class AgentEntityClaimResponse(BaseModel):
    entity_key: str
    session_id: str
    claimed_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    reason: str


class AgentHypothesisResponse(BaseModel):
    hypothesis_id: str
    statement: str
    scope: dict[str, str]
    priority: int
    status: str
    source_insight_id: str | None
    evidence_id: str | None
    evidence_outcome: str | None
    created_at: datetime
    updated_at: datetime
    depends_on: list[str] = Field(default_factory=list)
    insight_ids: list[str] = Field(default_factory=list)
    conclusion: dict[str, object] = Field(default_factory=dict)


class ComponentVersionReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component: Literal["model", "configuration", "library", "vector_store"]
    entity_id: str
    version: str
    content_sha256: str


class AgentExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    experiment_id: str
    iteration_number: int
    kind: Literal["ISOLATED", "COMBINATION"]
    status: Literal[
        "RUNNING",
        "SUCCEEDED",
        "REJECTED_GLOBAL_CONSTRAINT",
        "FAILED",
    ]
    components: list[ComponentVersionReferenceResponse]
    baseline_components: list[ComponentVersionReferenceResponse]
    snapshot_id: str | None = None
    snapshot_sha256: str | None = None
    objective_id: str
    objective_version: int
    created_at: datetime
    completed_at: datetime | None
    global_evaluation: dict[str, object]
    error_code: str | None
    candidate_id: str | None = None


class GenerateModusOperandiDraftRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    operation: Literal["create", "update"]
    target_id: str | None = None


class AgentDraftVerificationResponse(BaseModel):
    verification_id: str
    verifier: str
    status: str
    safe_metrics: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    created_at: datetime | None = None


class AgentDraftPackageResponse(BaseModel):
    package_id: str
    session_id: str
    status: str
    content_hash: str | None
    content: dict[str, object]
    verifications: list[AgentDraftVerificationResponse]


class ConfirmAgentDraftRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=128)


class ConfirmAgentDraftResponse(BaseModel):
    confirmation_id: str
    package_id: str
    item_id: str
    entity_id: str


class AgentConfirmationResponse(BaseModel):
    confirmation_id: str
    package_id: str
    item_id: str
    action: str
    content_hash: str
    confirmed_by: str
    confirmed_at: datetime
    status: str
    role: str
    base_version: str | None = None
    verification_states: dict[str, str] = Field(default_factory=dict)
    source_message_id: str | None = None


class AgentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    event_id: str
    occurred_at: datetime
    kind: str
    outcome: str
    summary: str
    reason_code: str | None = None
    refs: dict[str, str] = Field(default_factory=dict)
    duration_ms: int | None = None
    cost_micros: int | None = None
    actor_id: str | None = None


class AgentEventsPageResponse(BaseModel):
    items: list[AgentEventResponse]
    last_seq: int


class AgentVerdictResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    state: str
    title: str
    detail: str
    action: str | None = None
    code: str | None = None
    approval: Literal["budget", "candidates", "context"] | None = None
    retryable: bool = False


class AgentHealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lease: Literal["NONE", "ACTIVE", "EXPIRED"]
    stalled: bool
    last_event_at: datetime | None = None
    seconds_since_last_event: int | None = None


class AgentSessionOverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    status: str
    verdict: AgentVerdictResponse
    health: AgentHealthResponse
    iterations: dict[str, int] = Field(default_factory=dict)
    hypotheses: dict[str, int] = Field(default_factory=dict)
    experiments: dict[str, int] = Field(default_factory=dict)
    events_total: int = 0
    block: dict[str, object] = Field(default_factory=dict)


class ResolveAgentBlockRequest(BaseModel):
    kind: Literal["budget", "candidates", "context"]
    additions: dict[str, int] | None = None
    allowance: int | None = Field(default=None, ge=1, le=20)
    note: str | None = Field(default=None, max_length=1000)


class AgentFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding_id: str
    kind: str
    dimension: str
    dimension_value: str
    sample_count: int
    metrics: dict[str, float]
    source: str
    created_at: datetime
    opaque_refs: dict[str, str] = Field(default_factory=dict)


class OptimizerInsightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    insight_id: str
    statement: str
    kind: str
    scope_key: str
    status: str
    sample_count: int
    evidence_summary: dict[str, float] = Field(default_factory=dict)
    last_evaluated_at: datetime
    review_after: datetime
    origin_session_id: str | None = None


class AgentFailureResponse(BaseModel):
    code: str
    title: str
    detail: str
    action: str
    retryable: bool
    approval: Literal["budget", "candidates", "context"] | None = None


class RunWinnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    candidate_id: str
    experiment_id: str
    component: str
    recall: float
    precision: float
    recall_delta: float


class RunExperimentResponse(AgentExperimentResponse):
    events_stream: str


class RunCandidateResponse(BaseModel):
    hypothesis: AgentHypothesisResponse
    experiments: list[RunExperimentResponse] = Field(default_factory=list)


class OptimizationRunResponse(BaseModel):
    """The whole optimizer run in one structure (#29)."""

    run_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    objective_id: str | None = None
    objective_version: int | None = None
    baseline_components: list[ComponentVersionReferenceResponse] = Field(
        default_factory=list
    )
    budget_limits: dict[str, int] = Field(default_factory=dict)
    optimizer_settings: dict[str, object] = Field(default_factory=dict)
    scope_areas: list[str] = Field(default_factory=list)
    insight_ids: list[str] = Field(default_factory=list)
    memory_insight_ids: list[str] = Field(default_factory=list)
    winners: list[RunWinnerResponse] = Field(default_factory=list)
    winning_components: list[ComponentVersionReferenceResponse] = Field(
        default_factory=list
    )
    strategy: dict[str, object] = Field(default_factory=dict)
    events_stream: str = ""
    candidates: list[RunCandidateResponse] = Field(default_factory=list)
    findings: list[AgentFindingResponse] = Field(default_factory=list)
