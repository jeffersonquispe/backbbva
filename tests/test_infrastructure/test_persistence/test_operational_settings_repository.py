from __future__ import annotations

from datetime import datetime, timezone

from src.application.ports.configuration_port import (
    AnalystCapacity,
    DayProfile,
    ResolutionTag,
    ShortageBehavior,
    TestCleanupPolicy,
)
from src.application.ports.operational_settings_port import (
    OperationalSettings,
    OperationalSettingsChange,
    SettingChange,
)
from src.infrastructure.persistence.database.dynamodb.repositories.operational_settings_repository import (
    _change_from_item,
    _change_to_item,
    _from_item,
    _to_item,
)


def _settings(**overrides) -> OperationalSettings:
    defaults = dict(
        agent_enabled=True,
        analyst_escalation_enabled=True,
        voicebot_escalation_enabled=True,
        max_instances=8,
        auto_scale=True,
        voicebot_max_concurrent_calls=40,
        voicebot_shortage_behavior=ShortageBehavior(
            resolution_tag=ResolutionTag.BLOCK_SOFT
        ),
        analyst_capacity=AnalystCapacity(
            profiles=[DayProfile(id="regular", name="Día regular", description="", hourly=[4] * 24)],
            default_profile_id="regular",
            day_overrides={15: "pago"},
        ),
        analyst_shortage_behavior=ShortageBehavior(
            resolution_tag=ResolutionTag.SCALE_TO_ANALYST
        ),
        max_test_instances=4,
        max_concurrent_experiments=3,
        experiment_timeout_minutes=30,
        max_stored_test_runs=20,
        test_cleanup_policy=TestCleanupPolicy.OLDEST,
    )
    defaults.update(overrides)
    return OperationalSettings(**defaults)


def test_to_item_stringifies_day_override_keys() -> None:
    item = _to_item(_settings())

    assert item["record_id"] == "current"
    assert item["analyst_capacity"]["day_overrides"] == {"15": "pago"}


def test_item_round_trips_through_to_item_and_from_item() -> None:
    settings = _settings(agent_enabled=False, max_instances=12)

    restored = _from_item(_to_item(settings))

    assert restored == settings


def test_from_item_defaults_when_fields_missing() -> None:
    # Mirrors _ops_from_item's convention in configuration_repository.py:
    # a missing analyst_capacity falls back to an empty-profiles capacity,
    # not the dataclass's 2-seeded-profile default - repository.get()
    # itself only reaches OperationalSettings()'s real defaults when no
    # item exists at all (see DynamoOperationalSettingsRepository.get).
    restored = _from_item({"record_id": "current"})

    assert restored.agent_enabled is True
    assert restored.max_instances == 8
    assert restored.test_cleanup_policy == TestCleanupPolicy.OLDEST
    assert restored.analyst_capacity == AnalystCapacity(
        profiles=[], default_profile_id="regular", day_overrides={}
    )


def test_change_item_round_trips_with_json_encoded_values() -> None:
    change = OperationalSettingsChange(
        id="c1",
        changed_by="analyst@bbva.com",
        changed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        changes=[
            SettingChange("agent_enabled", True, False),
            SettingChange(
                "analyst_capacity.default_profile_id", "regular", "pago"
            ),
        ],
    )

    restored = _change_from_item(_change_to_item(change))

    assert restored == change
