from __future__ import annotations

import random

from src.application.ports.simulation_scenario_port import (
    FieldGenerator,
    GeneratorKind,
    RateInterval,
)

# Kinds resolved by this module's pure draw_structured_value() - the
# remaining two (TEMPLATE_LLM, SEED_RECREATION) need an LLM call and/or a
# DatasetReaderGateway round-trip, so GenerateEventBatchUseCase resolves
# those itself and only delegates the structured ones here.
STRUCTURED_KINDS = frozenset(
    {
        GeneratorKind.CONSTANT,
        GeneratorKind.CATEGORICAL,
        GeneratorKind.UNIFORM,
        GeneratorKind.NORMAL,
        GeneratorKind.LOGNORMAL,
        GeneratorKind.POISSON,
    }
)


def draw_structured_value(generator: FieldGenerator, rng: random.Random):
    if generator.kind == GeneratorKind.CONSTANT:
        return generator.value

    if generator.kind == GeneratorKind.CATEGORICAL:
        weights = generator.weights or {}
        if not weights:
            raise ValueError("CATEGORICAL generator requires non-empty weights")
        values = list(weights.keys())
        return rng.choices(values, weights=list(weights.values()), k=1)[0]

    params = generator.params or {}

    if generator.kind == GeneratorKind.UNIFORM:
        return rng.uniform(params["low"], params["high"])

    if generator.kind == GeneratorKind.NORMAL:
        return rng.gauss(params["mu"], params["sigma"])

    if generator.kind == GeneratorKind.LOGNORMAL:
        return rng.lognormvariate(params["mu"], params["sigma"])

    if generator.kind == GeneratorKind.POISSON:
        # stdlib random has no poisson draw; Knuth's algorithm is enough at
        # the small lambdas an event-count field realistically needs.
        return _draw_poisson(params["lambda"], rng)

    raise ValueError(f"Not a structured generator kind: {generator.kind}")


_KNUTH_LAMBDA_CUTOFF = 30.0  # e^-lambda underflows to exactly 0.0 well past
# this point, which would make Knuth's algorithm loop for hundreds of
# iterations doing meaningless work instead of terminating on a real draw -
# exactly the "high events_per_minute burst" scenario this simulator exists
# to support, so it has to be correct here too, not just at toy rates.


def _draw_poisson(lam: float, rng: random.Random) -> int:
    if lam <= 0:
        return 0
    if lam <= _KNUTH_LAMBDA_CUTOFF:
        limit = pow(2.718281828459045, -lam)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= rng.random()
            if p <= limit:
                return k - 1
    # Normal approximation (mean=lam, variance=lam) for large lambda - not
    # exact, but accurate enough for scheduling event counts, and O(1)
    # instead of Knuth's O(lambda) draws.
    draw = round(rng.gauss(lam, lam**0.5))
    return max(draw, 0)


def due_event_count(
    rate_schedule: list[RateInterval],
    window_start_seconds: int,
    window_end_seconds: int,
    rng: random.Random,
) -> int:
    """Poisson-samples how many events fall inside [window_start_seconds,
    window_end_seconds) given the scenario's arrival-rate curve, summing
    across every interval the window overlaps (a tick can straddle a rate
    change). events_per_minute=0 intervals and windows outside every
    interval contribute 0."""
    if window_end_seconds <= window_start_seconds:
        return 0

    total = 0
    for interval in rate_schedule:
        overlap_start = max(window_start_seconds, interval.start_offset_seconds)
        overlap_end = min(window_end_seconds, interval.end_offset_seconds)
        overlap_seconds = overlap_end - overlap_start
        if overlap_seconds <= 0 or interval.events_per_minute <= 0:
            continue
        expected = interval.events_per_minute * (overlap_seconds / 60.0)
        total += _draw_poisson(expected, rng)
    return total


def schedule_exhausted(rate_schedule: list[RateInterval], at_seconds: int) -> bool:
    return not any(
        interval.end_offset_seconds > at_seconds for interval in rate_schedule
    )
