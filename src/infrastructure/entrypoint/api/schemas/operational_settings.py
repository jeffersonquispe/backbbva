from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.domain.configurations.entities import (
    ListMembershipMode,
    SamplingIntervalUnit,
    TestCleanupPolicy,
)
from src.infrastructure.entrypoint.api.schemas.configuration import (
    AnalystCapacitySchema,
    ShortageBehaviorSchema,
)

# --- Operational settings -------------------------------------------------
# Admin-configured levers that take effect immediately, no version/activate
# lifecycle - see operational_settings_port.py. Reuses AnalystCapacitySchema/
# DayProfileSchema/ShortageBehaviorSchema/TestCleanupPolicy already defined
# above for the versioned configuration schemas.


class AmountTierSchema(BaseModel):
    code: str = Field(..., min_length=1, max_length=60)
    label: str = Field(default="", max_length=120)
    min_inclusive: float = Field(..., ge=0)
    # None = unbounded (the last tier).
    max_exclusive: float | None = None


class OperationalSettingsSchema(BaseModel):
    agent_enabled: bool = True
    analyst_enabled: bool = True
    voicebot_enabled: bool = True
    max_instances: int = 8
    auto_scale: bool = True
    voicebot_max_concurrent_calls: int = Field(default=40, ge=0, le=500)
    analyst_capacity: AnalystCapacitySchema = Field(
        default_factory=AnalystCapacitySchema
    )
    queue_max_lifetime_value: int = 60
    queue_max_lifetime_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    queue_discard_amount_threshold: float = 0
    queue_rule_filter_enabled: bool = False
    queue_rule_filter_mode: ListMembershipMode = ListMembershipMode.BELONGS
    queue_allowed_triggered_rules: list[str] = Field(default_factory=list)
    queue_discard_behavior: ShortageBehaviorSchema = Field(
        default_factory=ShortageBehaviorSchema
    )
    max_test_instances: int = 4
    max_concurrent_experiments: int = 3
    experiment_timeout_minutes: int = 30
    max_stored_test_runs: int = 20
    test_cleanup_policy: TestCleanupPolicy = TestCleanupPolicy.OLDEST
    # Request: omitted/None keeps the current tiers; [] clears them. Must be
    # contiguous, non-overlapping and cover 0 -> inf (else 422). Response:
    # always the full current list.
    amount_tiers: list[AmountTierSchema] | None = None
    # Share (0..1) of finished alerts sent to the reasoning LLM-judge;
    # 0 disables it.
    reasoning_evaluation_sample_rate: float = Field(default=0.05, ge=0, le=1)
    maturing_days: int = Field(default=4, ge=0, le=365)
    expected_coverage_pct: float = Field(default=98.0, gt=0, le=100)
    stable_months: int = Field(default=6, ge=0, le=120)


class UpdateOperationalSettingsRequest(BaseModel):
    settings: OperationalSettingsSchema
    # Free-text identifier captured for traceability only - not an enforced
    # identity, this codebase has no auth/permission system wired anywhere.
    changed_by: str | None = Field(default=None, max_length=120)


class SettingChangeResponse(BaseModel):
    path: str
    previous: Any
    new: Any


class OperationalSettingsChangeResponse(BaseModel):
    id: str
    changed_by: str | None
    changed_at: datetime
    changes: list[SettingChangeResponse]
