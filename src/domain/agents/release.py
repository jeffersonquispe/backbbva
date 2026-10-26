from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from src.domain.agents.experiment import ComponentVersionReference


class RetrospectiveValidationStatus(StrEnum):
    # The replay runs in the worker; the record is RUNNING until it finishes.
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AgentReleaseStatus(StrEnum):
    SHADOW = "SHADOW"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CANARY_5 = "CANARY_5"
    CANARY_25 = "CANARY_25"
    CANARY_50 = "CANARY_50"
    FULL = "FULL"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RetrospectiveValidation:
    validation_id: str
    session_id: str
    experiment_id: str
    status: RetrospectiveValidationStatus
    snapshot_id: str
    snapshot_sha256: str
    component_pins: tuple[ComponentVersionReference, ...]
    baseline_component_pins: tuple[ComponentVersionReference, ...]
    evidence: dict[str, Any]
    created_by: str
    created_by_id: str
    created_at: datetime
    error_code: str | None = None


@dataclass(frozen=True)
class AgentRelease:
    release_id: str
    validation_id: str
    session_id: str
    experiment_id: str
    status: AgentReleaseStatus
    candidate_component_pins: tuple[ComponentVersionReference, ...]
    previous_component_pins: tuple[ComponentVersionReference, ...]
    requested_by: str
    requested_by_id: str
    requested_at: datetime
    title: str
    reason: str
    snapshot_id: str = ""
    snapshot_sha256: str = ""
    rollout_policy_version: str = "h12_model_only_v1"
    version: int = 1
    approved_by: str | None = None
    approved_by_id: str | None = None
    approved_at: datetime | None = None
    updated_at: datetime | None = None
    observations: dict[str, Any] = field(default_factory=dict)
    rollback_reason: str | None = None
    # Non-model components handed to their existing promotion flow on approval:
    # component -> {"flow", "reference", "status"}.
    handoffs: dict[str, dict[str, str]] = field(default_factory=dict)
