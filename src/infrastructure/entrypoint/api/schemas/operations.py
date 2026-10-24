from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# --- Operations: live capacity, analyst queue, voicebot callback ---------


class ChannelCapacitySchema(BaseModel):
    available: int
    status: str
    total: int | None = None


class OperationsCapacityResponse(BaseModel):
    analysts: ChannelCapacitySchema
    voicebot: ChannelCapacitySchema
    bidi: ChannelCapacitySchema
    updated_at: datetime


class ResourceReservationResponse(BaseModel):
    id: str
    resource: str
    alert_id: str
    holder: str
    # Display name of the analyst holding it (None for a voicebot call or
    # an unknown user).
    holder_name: str | None = None
    reserved_at: datetime
    expires_at: datetime
    status: str
    released_at: datetime | None = None
    release_reason: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class AnalystQueueAlertResponse(BaseModel):
    alert_id: UUID
    event_id: str
    event_type: str
    status: str
    customer_id: str | None
    created_at: datetime
    # The canonical alert (docs/ALERT_SCHEMA_GOVERNANCE.md §3); the raw
    # payload is only served by GET /alerts/{id}/raw.
    schema_version: int | None = None
    configuration_ref: dict[str, Any] | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, Any] = Field(default_factory=dict)
    history_prev_alerta: list[dict[str, Any]] = Field(default_factory=list)
    agent_output: dict[str, Any] = Field(default_factory=dict)
    reservation: ResourceReservationResponse | None = None


class InProcessAlertResponse(BaseModel):
    """An alert ARIA is still analysing (not yet escalated or closed)."""

    alert_id: UUID
    event_id: str
    event_type: str
    status: str
    customer_id: str | None
    created_at: datetime
    schema_version: int | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    workflow_status: str | None = None
    # Workflow step running now (pre_process, classification, ...); None
    # before the workflow starts.
    current_step: str | None = None


class AnalystResolutionResponse(BaseModel):
    """How an analyst closed the alert."""

    decision: str
    notes: str = ""
    resolved_by: str | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None


class AlertStepResponse(BaseModel):
    step_name: str
    status: str
    attempt: int
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AlertDetailResponse(AnalystQueueAlertResponse):
    workflow_execution_id: UUID | None = None
    workflow_status: str | None = None
    workflow_output: dict[str, Any] | None = None
    steps: list[AlertStepResponse] = Field(default_factory=list)
    # Present only once an analyst closed the alert.
    analyst_resolution: AnalystResolutionResponse | None = None


class ResolveEscalatedAlertRequest(BaseModel):
    decision: Literal["block", "pass", "bidi"]
    notes: str = Field(default="", max_length=4000)


class VoicebotCallbackRequest(BaseModel):
    alert_id: UUID
    # Provider-defined result of the call (e.g. "confirmed_by_customer",
    # "fraud_reported", "no_answer") - stored as-is on the reservation.
    outcome: str = Field(..., min_length=1, max_length=120)
    detail: dict[str, Any] = Field(default_factory=dict)
