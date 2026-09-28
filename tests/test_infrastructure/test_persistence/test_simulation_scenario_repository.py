from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    OutputMode,
    RateInterval,
    ScenarioStatus,
    SimulationScenarioRecord,
)
from src.infrastructure.persistence.database.dynamodb.repositories.simulation_scenario_repository import (
    _from_item,
    _to_item,
)


def _make_scenario(**overrides) -> SimulationScenarioRecord:
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        name="burst test",
        status=ScenarioStatus.DRAFT,
        output_mode=OutputMode.DATASET,
        rate_schedule=[
            RateInterval(
                start_offset_seconds=0,
                end_offset_seconds=600,
                events_per_minute=5.5,
            ),
            RateInterval(
                start_offset_seconds=600,
                end_offset_seconds=900,
                events_per_minute=50.0,
            ),
        ],
        field_specs={
            "amount": FieldGenerator(
                kind=GeneratorKind.CONSTANT,
                value=100.25,
            ),
            "channel": FieldGenerator(
                kind=GeneratorKind.CATEGORICAL,
                weights={"web": 0.5, "mobile": 1.5},
            ),
            "delay_seconds": FieldGenerator(
                kind=GeneratorKind.UNIFORM,
                params={"low": 1.0, "high": 10.0},
            ),
            "risk_score": FieldGenerator(
                kind=GeneratorKind.NORMAL,
                params={"mu": 0.5, "sigma": 0.1},
            ),
            "amount_lognormal": FieldGenerator(
                kind=GeneratorKind.LOGNORMAL,
                params={"mu": 1.0, "sigma": 0.5},
            ),
            "event_count": FieldGenerator(
                kind=GeneratorKind.POISSON,
                params={"lambda": 3.0},
            ),
            "narrative": FieldGenerator(
                kind=GeneratorKind.TEMPLATE_LLM,
                system_prompt="You write fraud alert narratives.",
                user_prompt_template="Describe a transaction of {amount}",
                model="gpt-4o",
                temperature=0.7,
            ),
            "recreated_field": FieldGenerator(
                kind=GeneratorKind.SEED_RECREATION,
                system_prompt="Rewrite the seed value.",
                user_prompt_template="Vary {seed_value}",
                model="gpt-4o",
                temperature=0.3,
                seed_dataset_name="historical_alerts",
                seed_field="description",
            ),
        },
        created_at=now,
        updated_at=now,
        target_dataset_name="synthetic_alerts",
        created_by="cdrojasm@unal.edu.co",
        started_at=None,
        events_emitted=0,
        last_tick_offset_seconds=0,
        error=None,
    )
    defaults.update(overrides)
    return SimulationScenarioRecord(**defaults)


def test_round_trips_every_generator_kind_and_float_fields() -> None:
    scenario = _make_scenario()

    item = _to_item(scenario)
    restored = _from_item(item)

    assert restored == scenario


def test_serializes_floats_as_decimal_for_dynamodb() -> None:
    from decimal import Decimal

    scenario = _make_scenario()
    item = _to_item(scenario)

    assert item["field_specs"]["amount"]["value"] == Decimal("100.25")
    assert item["rate_schedule"][0]["events_per_minute"] == Decimal("5.5")
    assert item["field_specs"]["delay_seconds"]["params"]["low"] == Decimal("1.0")


def test_status_transition_round_trips() -> None:
    scenario = _make_scenario(
        status=ScenarioStatus.RUNNING,
        started_at=datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc),
        events_emitted=42,
        last_tick_offset_seconds=120,
    )

    restored = _from_item(_to_item(scenario))

    assert restored.status == ScenarioStatus.RUNNING
    assert restored.started_at == scenario.started_at
    assert restored.events_emitted == 42
    assert restored.last_tick_offset_seconds == 120


def test_error_field_round_trips_as_none_and_as_message() -> None:
    scenario = _make_scenario(status=ScenarioStatus.FAILED, error="LLM timeout")
    restored = _from_item(_to_item(scenario))
    assert restored.error == "LLM timeout"

    cleared = _make_scenario(status=ScenarioStatus.RUNNING, error=None)
    restored_cleared = _from_item(_to_item(cleared))
    assert restored_cleared.error is None
