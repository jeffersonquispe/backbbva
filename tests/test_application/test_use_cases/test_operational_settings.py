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


# --- amount tiers (C2) -------------------------------------------------------------

from src.application.ports.operational_settings_port import AmountTier  # noqa: E402
from src.domain.alerts.amount_tiers import InvalidAmountTiersError  # noqa: E402

_TIERS = [
    AmountTier("low", "< 1M", 0, 1_000_000),
    AmountTier("high", ">= 1M", 1_000_000, None),
]


def test_amount_tiers_default_to_empty() -> None:
    settings = OperationalSettings()
    assert settings.amount_tiers == [] and settings.amount_tier_set_version == 0


def test_changing_amount_tiers_bumps_version_and_records_history() -> None:
    repository = InMemoryOperationalSettingsRepository()
    use_case = UpdateOperationalSettingsUseCase(repository)

    first = use_case.execute(
        UpdateOperationalSettingsInput(
            settings=replace(OperationalSettings(), amount_tiers=_TIERS)
        )
    )
    assert first.amount_tier_set_version == 1
    paths = {c.path for c in repository.history[-1].changes}
    assert {"amount_tiers", "amount_tier_set_version"} <= paths
    tiers_change = next(c for c in repository.history[-1].changes if c.path == "amount_tiers")
    assert tiers_change.previous == [] and tiers_change.new[0]["code"] == "low"

    # Unrelated change: version stays, even if the client sends another one.
    second = use_case.execute(
        UpdateOperationalSettingsInput(
            settings=replace(first, agent_enabled=False, amount_tier_set_version=99)
        )
    )
    assert second.amount_tier_set_version == 1

    third = use_case.execute(
        UpdateOperationalSettingsInput(settings=replace(second, amount_tiers=[]))
    )
    assert third.amount_tier_set_version == 2


def test_invalid_amount_tiers_are_rejected_and_nothing_is_saved() -> None:
    repository = InMemoryOperationalSettingsRepository()
    gap = [AmountTier("a", "a", 0, 10), AmountTier("b", "b", 20, None)]
    try:
        UpdateOperationalSettingsUseCase(repository).execute(
            UpdateOperationalSettingsInput(
                settings=replace(OperationalSettings(), amount_tiers=gap)
            )
        )
    except InvalidAmountTiersError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected InvalidAmountTiersError")
    assert repository.update_calls == []


def test_preserve_amount_tiers_keeps_current_set() -> None:
    repository = InMemoryOperationalSettingsRepository(
        replace(OperationalSettings(), amount_tiers=_TIERS, amount_tier_set_version=4)
    )
    updated = UpdateOperationalSettingsUseCase(repository).execute(
        UpdateOperationalSettingsInput(
            settings=OperationalSettings(agent_enabled=False),
            preserve_amount_tiers=True,
        )
    )
    assert updated.amount_tiers == _TIERS
    assert updated.amount_tier_set_version == 4
