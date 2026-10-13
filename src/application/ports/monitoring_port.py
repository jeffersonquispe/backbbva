from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.application.ports.alert_port import AlertMetricsSnapshot

# --- Span attribute names (T2) -----------------------------------------------
# The single source for the alert-dimension attributes put on spans. Same
# names as the AlertMetricsSnapshot fields (alert_port.py), prefixed
# `aria.`, so a trace can be filtered with the dashboard's own dimensions.
# FORBIDDEN on spans (never add a constant for them): `customer_id` and the
# exact `amount` - only the amount *tier* may leave the process.
ATTR_ALERT_ID = "alert_id"
ATTR_WORKFLOW_EXECUTION_ID = "workflow_execution_id"
ATTR_ORIGIN = "aria.origin"
ATTR_SEGMENT = "aria.segment"
ATTR_CHANNEL = "aria.channel"
ATTR_SUBCHANNEL = "aria.subchannel"
ATTR_AMOUNT_TIER = "aria.amount_tier"
ATTR_CONFIGURATION_ID = "aria.configuration_id"
ATTR_RESOLUTION_METHOD = "aria.resolution_method"
ATTR_MARK = "aria.mark"
ATTR_FRAUD_LABEL = "aria.fraud_label"
ATTR_STATUS = "aria.status"
# Measures/extra facts of the dedicated mark / fraud_label review spans.
ATTR_RESOLUTION_TIME_SECONDS = "aria.resolution_time_seconds"
ATTR_PREVIOUS_FRAUD_LABEL = "aria.fraud_label.previous"
ATTR_FRAUD_REVIEW_CHANNEL = "aria.fraud_review.channel"
ATTR_FRAUD_REVIEW_COUNT = "aria.fraud_review.count"
ATTR_WORKFLOW_STEP = "aria.workflow.step"
ATTR_WORKFLOW_ATTEMPT = "aria.workflow.attempt"
ATTR_WORKFLOW_OUTCOME = "aria.workflow.outcome"

# AlertMetricsSnapshot field -> span attribute. Deliberately excludes
# `amount` (exact value) and every timestamp/counter field.
SNAPSHOT_SPAN_ATTRIBUTES: dict[str, str] = {
    "origin": ATTR_ORIGIN,
    "segment": ATTR_SEGMENT,
    "channel": ATTR_CHANNEL,
    "subchannel": ATTR_SUBCHANNEL,
    "amount_tier": ATTR_AMOUNT_TIER,
    "configuration_id": ATTR_CONFIGURATION_ID,
    "resolution_method": ATTR_RESOLUTION_METHOD,
    "mark": ATTR_MARK,
    "fraud_label": ATTR_FRAUD_LABEL,
    "status": ATTR_STATUS,
}


def span_dimension_attributes(
    snapshot: AlertMetricsSnapshot | None,
) -> dict[str, str]:
    """The alert's known dimensions as span attributes (unknown/None ones
    are left out). Never carries customer_id or the exact amount."""
    if snapshot is None:
        return {}
    attributes: dict[str, str] = {}
    for field_name, attribute in SNAPSHOT_SPAN_ATTRIBUTES.items():
        value = getattr(snapshot, field_name, None)
        if value is not None:
            attributes[attribute] = str(value)
    return attributes


# `step` value for `record_workflow_duration` that covers a whole alert
# review run (first step start -> terminal status), as opposed to one of the
# individual LINEAR_STEPS.
WORKFLOW_TOTAL_STEP = "workflow"


class MonitoringStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ResearchCallOutcome(StrEnum):
    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class OperationalStateSnapshot:
    """Point-in-time operational gauges (one sample per scheduler tick).

    Backs the "stuck queue", "no capacity" and "dead man's switch" monitors.
    """

    agent_enabled: bool
    within_operating_hours: bool
    analyst_queue_depth: int
    analyst_queue_oldest_age_seconds: float
    analysts_available: int
    voicebot_slots_available: int


class MonitoringSpan(ABC):
    """One tracked operation instance.

    Start time and execution time are handled by the implementation
    (recorded on creation and on `finish`); callers only report the
    operation-specific facts.
    """

    @abstractmethod
    def write_input(self, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def write_result(self, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def write_inner_logs(
        self, entries: dict[str, Any] | list[dict[str, Any]]
    ) -> None: ...

    @abstractmethod
    def write_operation_metas(self, metadata: dict[str, Any]) -> None: ...

    @abstractmethod
    def record_dependency(
        self,
        name: str,
        kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    @abstractmethod
    def finish(self, error: str | None = None) -> None: ...

    def __enter__(self) -> MonitoringSpan:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.finish(str(exc) if exc is not None else None)


class MonitoringPort(ABC):
    @abstractmethod
    def start(
        self,
        operation_name: str,
        operation_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> MonitoringSpan: ...

    # Explicit metrics. Concrete no-ops (not abstract) on purpose: existing
    # adapters and test fakes keep working without overriding them. Every
    # argument becomes a metric dimension, so pass only low-cardinality
    # values (step names, enum outcomes) - never customer ids, alert ids or
    # exact amounts.

    def record_workflow_duration(
        self, step: str, outcome: str, duration_seconds: float
    ) -> None:
        """One finished workflow step, or the whole run when
        `step == WORKFLOW_TOTAL_STEP`. `outcome` is the final status
        (e.g. CLOSED/ESCALATED/FAILED/SKIPPED, SUCCEEDED/FAILED)."""

    def record_research_call(
        self, source: str, outcome: ResearchCallOutcome
    ) -> None:
        """One research lookup (`source`: e.g. "vector_store",
        "alert_history")."""

    def record_rollup_drift(
        self, data_type: str, level: str, drift: float
    ) -> None:
        """Result of one metrics-rollup reconciliation: how far the stored
        aggregate was from the recomputed one (0 = consistent) for a
        `data_type` (alert, workflow_step, ...) and `level` (day/month/year).
        Last value wins until the next reconciliation."""

    def record_operational_state(
        self, snapshot: OperationalStateSnapshot
    ) -> None:
        """Current queue/capacity/agent state; call periodically."""
