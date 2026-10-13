from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from src.application.ports.configuration_port import (
    AnalystCapacity,
    ListMembershipMode,
    SamplingIntervalUnit,
    ShortageBehavior,
    TestCleanupPolicy,
)
# AmountTier lives in the domain (domain/alerts/amount_tiers.py) next to
# classify_amount/validate_amount_tiers; re-exported here as part of this
# port's contract.
from src.domain.alerts.amount_tiers import AmountTier  # noqa: F401  (re-export)


@dataclass
class OperationalSettings:
    """Admin-configured operational levers that take effect immediately -
    no version/activate lifecycle, unlike ConfigurationRecord
    (configuration_port.py). Everything that must react right away lives
    here and never in a versioned configuration: the agent/analyst/voicebot
    on-off switches, resource sizing (voicebot slots, the analyst staffing
    matrix) and queue handling.

    Resource *availability* is derived from these at read time by
    GetOperationsCapacityUseCase (current matrix hour / slot quota minus
    active reservations, or 0 when the resource is off). What to do when a
    resource is short is NOT a resource setting: it belongs to each modus
    operandi playbook's fallback chain (modus_operandi_library_port.py)."""

    # OFF: manual runs and CSV batch runs still process; simulator and
    # production alerts are skipped by the worker (see AlertOrigin).
    agent_enabled: bool = True
    # OFF: analyst availability reads as 0 / "unavailable".
    analyst_enabled: bool = True
    # OFF: voicebot availability reads as 0 / "unavailable".
    voicebot_enabled: bool = True

    max_instances: int = 8
    auto_scale: bool = True

    # Fixed quota of voicebot slots: a call holds one until its callback
    # arrives (or the reservation TTL expires).
    voicebot_max_concurrent_calls: int = 40
    analyst_capacity: AnalystCapacity = field(default_factory=AnalystCapacity)

    queue_max_lifetime_value: int = 60
    queue_max_lifetime_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    queue_discard_amount_threshold: float = 0
    # When enabled, alerts are filtered by whether their triggered_rule tag
    # belongs to queue_allowed_triggered_rules (per queue_rule_filter_mode).
    queue_rule_filter_enabled: bool = False
    queue_rule_filter_mode: ListMembershipMode = ListMembershipMode.BELONGS
    queue_allowed_triggered_rules: list[str] = field(default_factory=list)
    # What to do with an alert instead of queuing it normally, whenever any
    # of the queue-discard paths above trigger.
    queue_discard_behavior: ShortageBehavior = field(
        default_factory=ShortageBehavior
    )

    max_test_instances: int = 4
    max_concurrent_experiments: int = 3
    experiment_timeout_minutes: int = 30
    max_stored_test_runs: int = 20
    test_cleanup_policy: TestCleanupPolicy = TestCleanupPolicy.OLDEST

    # Ranges an alert's amount is classified into when it arrives (frozen on
    # its metrics snapshot). Empty = every amount is "unknown". Must be a
    # contiguous, non-overlapping cover of 0 -> inf when non-empty
    # (validate_amount_tiers).
    amount_tiers: list[AmountTier] = field(default_factory=list)

    # Share (0..1) of alerts whose finished review is sent to the LLM-judge
    # (EvaluateAlertReasoning, the /monitor "Alucinaciones" / "Uso correcto
    # de datos" KPIs). 0 disables it. Sampling is deterministic per alert.
    reasoning_evaluation_sample_rate: float = 0.05


@dataclass(frozen=True)
class SettingChange:
    path: str
    previous: Any
    new: Any


@dataclass(frozen=True)
class OperationalSettingsChange:
    id: str
    changed_by: str | None
    changed_at: datetime
    changes: list[SettingChange]


class OperationalSettingsRepository(Protocol):
    def get(self) -> OperationalSettings:
        """Current singleton settings, or defaults if never written."""
        ...

    def update(
        self, settings: OperationalSettings, change: OperationalSettingsChange
    ) -> OperationalSettings:
        """Replaces the current singleton settings and appends the given
        change record to history. Diffing happens in the use case, not
        here - this repository just persists what it's given."""
        ...

    def list_changes(self, limit: int = 50) -> list[OperationalSettingsChange]:
        ...
