from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

GLOBAL_FRAUD_OBJECTIVE_ID = "global_fraud_effectiveness"


class AgentObjectiveStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class AgentObjective:
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
    approved_by: str | None = None
    activated_at: datetime | None = None

