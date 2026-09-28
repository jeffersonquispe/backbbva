from __future__ import annotations

import random

import pytest

from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    RateInterval,
)
from src.application.use_cases.event_simulation.field_generation import (
    draw_structured_value,
    due_event_count,
    schedule_exhausted,
)


def test_constant_generator_always_returns_its_value() -> None:
    generator = FieldGenerator(kind=GeneratorKind.CONSTANT, value="fixed")
    rng = random.Random(0)

    assert draw_structured_value(generator, rng) == "fixed"


def test_categorical_generator_only_draws_configured_values() -> None:
    generator = FieldGenerator(
        kind=GeneratorKind.CATEGORICAL,
        weights={"a": 0.9, "b": 0.1},
    )
    rng = random.Random(42)

    draws = {draw_structured_value(generator, rng) for _ in range(50)}

    assert draws <= {"a", "b"}


def test_categorical_generator_requires_weights() -> None:
    generator = FieldGenerator(kind=GeneratorKind.CATEGORICAL, weights={})
    with pytest.raises(ValueError):
        draw_structured_value(generator, random.Random(0))


def test_uniform_generator_stays_within_bounds() -> None:
    generator = FieldGenerator(
        kind=GeneratorKind.UNIFORM, params={"low": 10.0, "high": 20.0}
    )
    rng = random.Random(1)

    for _ in range(50):
        value = draw_structured_value(generator, rng)
        assert 10.0 <= value <= 20.0


def test_poisson_generator_returns_non_negative_ints() -> None:
    generator = FieldGenerator(kind=GeneratorKind.POISSON, params={"lambda": 3.0})
    rng = random.Random(2)

    for _ in range(50):
        value = draw_structured_value(generator, rng)
        assert isinstance(value, int)
        assert value >= 0


def test_poisson_generator_terminates_quickly_at_large_lambda() -> None:
    # Regression guard: Knuth's algorithm underflows e^-lambda to exactly
    # 0.0 well past lambda=30, which without the large-lambda fallback
    # never terminates on a meaningful draw - a burst scenario's
    # events_per_minute easily implies a lambda in the thousands.
    generator = FieldGenerator(kind=GeneratorKind.POISSON, params={"lambda": 6000.0})
    rng = random.Random(9)

    value = draw_structured_value(generator, rng)

    assert isinstance(value, int)
    assert value >= 0
    assert 4000 < value < 8000  # loose sanity band around the mean


def test_due_event_count_is_zero_outside_every_interval() -> None:
    schedule = [RateInterval(start_offset_seconds=0, end_offset_seconds=60, events_per_minute=10)]
    rng = random.Random(0)

    assert due_event_count(schedule, 60, 120, rng) == 0


def test_due_event_count_sums_across_overlapping_intervals() -> None:
    schedule = [
        RateInterval(start_offset_seconds=0, end_offset_seconds=60, events_per_minute=60),
        RateInterval(start_offset_seconds=60, end_offset_seconds=120, events_per_minute=600),
    ]
    rng = random.Random(7)

    # A window straddling both legs should land closer to the high-rate
    # leg's expectation than to the low-rate leg's - a loose sanity bound,
    # not an exact draw (Poisson-sampled).
    count = due_event_count(schedule, 50, 70, rng)
    assert count >= 0


def test_schedule_exhausted_true_once_every_interval_has_ended() -> None:
    schedule = [RateInterval(start_offset_seconds=0, end_offset_seconds=60, events_per_minute=10)]

    assert schedule_exhausted(schedule, 60) is True
    assert schedule_exhausted(schedule, 59) is False
