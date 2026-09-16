from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from src.application.ports.configuration_port import (
    AnalystCapacity,
    ShortageBehavior,
    TestCleanupPolicy,
)


@dataclass
class OperationalSettings:
    """Admin-configured operational levers that take effect immediately -
    no version/activate lifecycle, unlike ConfigurationRecord
    (configuration_port.py). Distinct from OperationsCapacityPort's
    OperationsCapacityRecord (operations_capacity_port.py): that one is a
    live current-availability snapshot (analysts/voicebot/bidi, "available"
    + "status") read by the analyst-review workflow at decision time; this
    is the admin-set target/ceiling/schedule those numbers would eventually
    be measured against (voicebot_max_concurrent_calls is the ceiling,
    analyst_capacity is the staffing plan) - the two aren't wired together
    yet, that link is a separate piece of work."""

    agent_enabled: bool = True
    analyst_escalation_enabled: bool = True
    voicebot_escalation_enabled: bool = True

    max_instances: int = 8
    auto_scale: bool = True

    voicebot_max_concurrent_calls: int = 40
    voicebot_shortage_behavior: ShortageBehavior = field(
        default_factory=ShortageBehavior
    )
    analyst_capacity: AnalystCapacity = field(default_factory=AnalystCapacity)
    analyst_shortage_behavior: ShortageBehavior = field(
        default_factory=ShortageBehavior
    )

    max_test_instances: int = 4
    max_concurrent_experiments: int = 3
    experiment_timeout_minutes: int = 30
    max_stored_test_runs: int = 20
    test_cleanup_policy: TestCleanupPolicy = TestCleanupPolicy.OLDEST


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
