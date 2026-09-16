from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from src.application.dtos.operational_settings_dtos import (
    UpdateOperationalSettingsInput,
)
from src.application.ports.operational_settings_port import (
    OperationalSettings,
    OperationalSettingsChange,
    SettingChange,
)
from src.application.use_cases.operational_settings.get_operational_settings import (
    GetOperationalSettingsUseCase,
)
from src.application.use_cases.operational_settings.list_operational_settings_history import (
    ListOperationalSettingsHistoryUseCase,
)
from src.application.use_cases.operational_settings.update_operational_settings import (
    UpdateOperationalSettingsUseCase,
)


class InMemoryOperationalSettingsRepository:
    def __init__(self, initial: OperationalSettings | None = None) -> None:
        self.settings = initial or OperationalSettings()
        self.history: list[OperationalSettingsChange] = []
        self.update_calls: list[tuple[OperationalSettings, OperationalSettingsChange]] = []

    def get(self) -> OperationalSettings:
        return self.settings

    def update(
        self, settings: OperationalSettings, change: OperationalSettingsChange
    ) -> OperationalSettings:
        self.update_calls.append((settings, change))
        self.settings = settings
        self.history.append(change)
        return settings

    def list_changes(self, limit: int = 50) -> list[OperationalSettingsChange]:
        return list(reversed(self.history))[:limit]


def test_get_operational_settings_returns_current_singleton() -> None:
    repository = InMemoryOperationalSettingsRepository(
        OperationalSettings(agent_enabled=False)
    )

    result = GetOperationalSettingsUseCase(repository).execute()

    assert result.agent_enabled is False


def test_update_operational_settings_persists_new_value_and_records_change() -> None:
    repository = InMemoryOperationalSettingsRepository()
    use_case = UpdateOperationalSettingsUseCase(repository)

    updated = use_case.execute(
        UpdateOperationalSettingsInput(
            settings=replace(repository.get(), agent_enabled=False),
            changed_by="analyst@bbva.com",
        )
    )

    assert updated.agent_enabled is False
    assert repository.get().agent_enabled is False
    assert len(repository.history) == 1
    change = repository.history[0]
    assert change.changed_by == "analyst@bbva.com"
    assert change.changes == [SettingChange("agent_enabled", True, False)]


def test_update_operational_settings_diffs_nested_field() -> None:
    repository = InMemoryOperationalSettingsRepository()
    use_case = UpdateOperationalSettingsUseCase(repository)
    new_capacity = replace(
        repository.get().analyst_capacity, default_profile_id="pago"
    )

    use_case.execute(
        UpdateOperationalSettingsInput(
            settings=replace(repository.get(), analyst_capacity=new_capacity),
            changed_by=None,
        )
    )

    change = repository.history[0]
    paths = {c.path for c in change.changes}
    assert "analyst_capacity.default_profile_id" in paths


def test_update_operational_settings_records_no_changes_when_nothing_differs() -> None:
    repository = InMemoryOperationalSettingsRepository()
    use_case = UpdateOperationalSettingsUseCase(repository)

    use_case.execute(
        UpdateOperationalSettingsInput(settings=repository.get(), changed_by=None)
    )

    assert repository.history[0].changes == []


def test_list_operational_settings_history_returns_most_recent_first() -> None:
    repository = InMemoryOperationalSettingsRepository()
    older = OperationalSettingsChange(
        id="1", changed_by=None, changed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), changes=[]
    )
    newer = OperationalSettingsChange(
        id="2", changed_by=None, changed_at=datetime(2026, 1, 2, tzinfo=timezone.utc), changes=[]
    )
    repository.history = [older, newer]

    result = ListOperationalSettingsHistoryUseCase(repository).execute(limit=1)

    assert result == [newer]
