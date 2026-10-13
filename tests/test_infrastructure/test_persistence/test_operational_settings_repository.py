from __future__ import annotations

from datetime import UTC, datetime

from src.application.ports.configuration_port import (
    AnalystCapacity,
    DayProfile,
    ListMembershipMode,
    ResolutionTag,
    SamplingIntervalUnit,
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
        analyst_enabled=True,
        voicebot_enabled=True,
        max_instances=8,
        auto_scale=True,
        voicebot_max_concurrent_calls=40,
        analyst_capacity=AnalystCapacity(
            profiles=[DayProfile(id="regular", name="Día regular", description="", hourly=[4] * 24)],
            default_profile_id="regular",
            day_overrides={15: "pago"},
        ),
        queue_max_lifetime_value=2,
        queue_max_lifetime_unit=SamplingIntervalUnit.HOURS,
        queue_discard_amount_threshold=1500.5,
        queue_rule_filter_enabled=True,
        queue_rule_filter_mode=ListMembershipMode.NOT_BELONGS,
        queue_allowed_triggered_rules=["CUSTOMER - dg_no_digital"],
        queue_discard_behavior=ShortageBehavior(
            resolution_tag=ResolutionTag.BLOCK_HARD, resolution_method_id="rm-1"
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
    settings = _settings(
        agent_enabled=False,
        analyst_enabled=False,
        voicebot_enabled=False,
        max_instances=12,
    )

    restored = _from_item(_to_item(settings))

    assert restored == settings


def test_from_item_defaults_when_fields_missing() -> None:
    # A missing analyst_capacity falls back to the dataclass default (two
    # seeded profiles), so a fresh singleton never reads as 0 analysts.
    restored = _from_item({"record_id": "current"})

    assert restored == OperationalSettings()


def test_from_item_reads_pre_rename_switches() -> None:
    restored = _from_item(
        {
            "record_id": "current",
            "analyst_escalation_enabled": False,
            "voicebot_escalation_enabled": False,
        }
    )

    assert restored.analyst_enabled is False
    assert restored.voicebot_enabled is False


def test_change_item_round_trips_with_json_encoded_values() -> None:
    change = OperationalSettingsChange(
        id="c1",
        changed_by="analyst@bbva.com",
        changed_at=datetime(2026, 1, 1, tzinfo=UTC),
        changes=[
            SettingChange("agent_enabled", True, False),
            SettingChange(
                "analyst_capacity.default_profile_id", "regular", "pago"
            ),
        ],
    )

    restored = _change_from_item(_change_to_item(change))

    assert restored == change


def test_amount_tiers_round_trip_and_old_items_default_empty() -> None:
    from decimal import Decimal

    from src.application.ports.operational_settings_port import AmountTier

    settings = _settings(
        amount_tiers=[
            AmountTier("low", "< 1.5M", 0, 1_500_000.5),
            AmountTier("high", ">= 1.5M", 1_500_000.5, None),
        ],
    )
    item = _to_item(settings)
    assert item["amount_tiers"][0]["max_exclusive"] == Decimal("1500000.5")
    assert item["amount_tiers"][1]["max_exclusive"] is None

    restored = _from_item(item)
    assert restored.amount_tiers == settings.amount_tiers

    legacy = {k: v for k, v in item.items() if not k.startswith("amount_tier")}
    old = _from_item(legacy)
    assert old.amount_tiers == []
