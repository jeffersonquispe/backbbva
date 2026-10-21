from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.domain.agents.objective import AgentObjectiveStatus


class AgentObjectiveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    objective_id: str
    version: int
    success_label: str
    positive_label: str
    negative_label: str
    maturing_days: int
    expected_coverage_pct: float
    stable_months: int
    primary_metrics: tuple[str, ...]
    precision_floor: float
    minimum_support_per_segment: int
    minimum_global_support: int
    minimum_count_to_publish_aggregates: int
    minimum_mature_alert_coverage_pct: float
    unlabeled_rule: str
    schema_mapping: dict[str, Any]
    status: AgentObjectiveStatus
    created_by: str
    created_at: datetime
    approved_by: str | None
    activated_at: datetime | None
    knowledge_decision_policy: str


class ActivateAgentObjectiveRequest(BaseModel):
    expected_active_version: int | None


class StartGlobalPipelineEvaluationRequest(BaseModel):
    snapshot_id: str
    candidate_model_id: str


class GlobalPipelineEvaluationResponse(BaseModel):
    snapshot_id: str
    status: str
    verifier: str
    safe_metrics: dict[str, Any]
    error_code: str | None = None
