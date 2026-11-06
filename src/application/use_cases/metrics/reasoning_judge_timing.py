"""How long will the LLM-judge take, and does the evaluator keep up?

Pure arithmetic over measured judge calls, so the projection is testable without
a model: per-call latency (p50/p95), tokens, and - given how many alerts arrive
per day, the sample rate and the evaluator's workers - its utilization and the
expected wait in the queue at an average and at a peak hour (M/M/c, Erlang C).
The calls themselves are measured by ``reasoning_judge_benchmark``."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Alerts do not arrive evenly; this is how much busier the busiest hour is than
# the average hour (adjust with real traffic from the metrics dashboard).
DEFAULT_PEAK_FACTOR = 3.0


@dataclass(frozen=True)
class JudgeCall:
    duration_ms: int
    input_tokens: int
    output_tokens: int
    attempts: int = 1


@dataclass(frozen=True)
class LoadProjection:
    arrivals_per_hour: float
    utilization: float
    # Expected wait for a worker before the judge starts (seconds); None when
    # the evaluator cannot keep up (utilization >= 1: the queue grows forever).
    expected_wait_s: float | None
    keeps_up: bool


@dataclass(frozen=True)
class TimingReport:
    calls: int
    p50_ms: int
    p95_ms: int
    max_ms: int
    mean_ms: float
    mean_tokens: float
    retried_share: float
    evaluations_per_day: float
    tokens_per_day: float
    hourly_capacity: float
    average_hour: LoadProjection
    peak_hour: LoadProjection


def percentile(values: list[int], fraction: float) -> int:
    """Nearest-rank percentile; 0 for an empty list."""
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def _erlang_c(servers: int, offered_load: float) -> float:
    """Probability an arrival has to wait (M/M/c). Needs offered_load < servers."""
    terms = 1.0
    term = 1.0
    for k in range(1, servers):
        term *= offered_load / k
        terms += term
    last = term * offered_load / servers * (servers / (servers - offered_load))
    return last / (terms + last)


def project_load(
    mean_service_s: float, workers: int, arrivals_per_hour: float
) -> LoadProjection:
    if workers < 1 or mean_service_s <= 0:
        raise ValueError("workers must be >= 1 and the service time positive")
    arrival_rate = arrivals_per_hour / 3600
    offered = arrival_rate * mean_service_s
    utilization = offered / workers
    if utilization >= 1:
        return LoadProjection(arrivals_per_hour, utilization, None, False)
    if offered == 0:
        return LoadProjection(arrivals_per_hour, 0.0, 0.0, True)
    wait_probability = _erlang_c(workers, offered)
    expected_wait = wait_probability * mean_service_s / (workers - offered)
    return LoadProjection(arrivals_per_hour, utilization, expected_wait, True)


def summarize(
    calls: list[JudgeCall],
    *,
    alerts_per_day: float,
    sample_rate: float,
    workers: int,
    peak_factor: float = DEFAULT_PEAK_FACTOR,
) -> TimingReport:
    if not calls:
        raise ValueError("no judge calls to summarize")
    durations = [c.duration_ms for c in calls]
    mean_ms = sum(durations) / len(durations)
    mean_tokens = sum(c.input_tokens + c.output_tokens for c in calls) / len(calls)
    evaluations_per_day = alerts_per_day * max(0.0, min(sample_rate, 1.0))
    average_per_hour = evaluations_per_day / 24
    mean_s = mean_ms / 1000
    return TimingReport(
        calls=len(calls),
        p50_ms=percentile(durations, 0.5),
        p95_ms=percentile(durations, 0.95),
        max_ms=max(durations),
        mean_ms=mean_ms,
        mean_tokens=mean_tokens,
        retried_share=sum(1 for c in calls if c.attempts > 1) / len(calls),
        evaluations_per_day=evaluations_per_day,
        tokens_per_day=evaluations_per_day * mean_tokens,
        hourly_capacity=workers * 3600 / mean_s if mean_s > 0 else float("inf"),
        average_hour=project_load(mean_s, workers, average_per_hour),
        peak_hour=project_load(mean_s, workers, average_per_hour * peak_factor),
    )
