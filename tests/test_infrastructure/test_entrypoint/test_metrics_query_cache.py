"""A4: the 60 s per-query cache in front of the /metrics read use cases -
hits within the TTL, expiry, key normalization (hour slots, filter order,
defaults), re-stamped range, errors never cached, LRU bound."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

os.environ.setdefault("GENAI_ENVIRONMENT", "test")

import pytest

from src.application.dtos.metrics_dtos import MetricsQueryInput, MetricsRange
from src.infrastructure.entrypoint.api.metrics_query_cache import (
    CachedMetricsQuery,
    TTLCache,
)

NOW = datetime(2026, 10, 1, 15, 5, 12, tzinfo=UTC)


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


@dataclass
class FakeOutput:
    range: MetricsRange
    total: int


@dataclass
class RecordingQuery:
    """Stands in for GetMetricsOverview & co.: counts executions and
    returns a new total each time, so a cache hit is observable."""

    calls: list[MetricsQueryInput] = field(default_factory=list)

    def execute(self, input: MetricsQueryInput) -> FakeOutput:
        if input.filters.get("bad"):
            raise ValueError("unknown filter")
        self.calls.append(input)
        to = input.to or NOW
        return FakeOutput(
            range=MetricsRange(from_=input.from_ or to - timedelta(hours=24), to=to, timezone="America/Bogota"),
            total=len(self.calls),
        )


def _cached(monotonic: FakeMonotonic, now: datetime = NOW, endpoint: str = "overview"):
    inner = RecordingQuery()
    cache = TTLCache(ttl_seconds=60, max_entries=3, monotonic=monotonic)
    return inner, cache, CachedMetricsQuery(endpoint, inner, cache, clock=lambda: now)


def _input(from_: datetime, to: datetime, **filters: list[str]) -> MetricsQueryInput:
    return MetricsQueryInput(from_=from_, to=to, filters=dict(filters))


def test_same_query_within_ttl_is_served_from_cache() -> None:
    monotonic = FakeMonotonic()
    inner, _, cached = _cached(monotonic)
    query = _input(NOW - timedelta(days=90), NOW, channel=["APP"])

    first = cached.execute(query)
    monotonic.value += 59
    second = cached.execute(query)

    assert len(inner.calls) == 1
    assert first.total == second.total == 1


def test_entry_expires_after_the_ttl() -> None:
    monotonic = FakeMonotonic()
    inner, _, cached = _cached(monotonic)
    query = _input(NOW - timedelta(days=7), NOW)

    cached.execute(query)
    monotonic.value += 61
    again = cached.execute(query)

    assert len(inner.calls) == 2
    assert again.total == 2


def test_ranges_reading_the_same_hour_slots_share_an_entry_and_keep_their_own_range() -> None:
    inner, _, cached = _cached(FakeMonotonic())
    a = _input(datetime(2026, 9, 30, 15, 0, 1, tzinfo=UTC), datetime(2026, 10, 1, 15, 0, 1, tzinfo=UTC))
    b = _input(datetime(2026, 9, 30, 15, 40, tzinfo=UTC), datetime(2026, 10, 1, 15, 40, tzinfo=UTC))

    cached.execute(a)
    out_b = cached.execute(b)

    assert len(inner.calls) == 1
    assert (out_b.range.from_, out_b.range.to) == (b.from_, b.to)


def test_a_different_hour_slot_is_a_different_entry() -> None:
    inner, _, cached = _cached(FakeMonotonic())
    # from 15:00:00 reads slot 15; from 15:00:01 starts at slot 16.
    cached.execute(_input(datetime(2026, 9, 30, 15, 0, tzinfo=UTC), NOW))
    cached.execute(_input(datetime(2026, 9, 30, 15, 0, 1, tzinfo=UTC), NOW))

    assert len(inner.calls) == 2


def test_filters_are_normalized_and_part_of_the_key() -> None:
    inner, _, cached = _cached(FakeMonotonic())
    from_ = NOW - timedelta(days=30)

    cached.execute(_input(from_, NOW, channel=["WEB", "APP"], segment=["retail"]))
    cached.execute(_input(from_, NOW, segment=["retail"], channel=["APP", "WEB"]))
    cached.execute(_input(from_, NOW, channel=["APP"]))

    assert len(inner.calls) == 2


def test_default_range_is_resolved_before_keying() -> None:
    inner, _, cached = _cached(FakeMonotonic())

    cached.execute(MetricsQueryInput())
    cached.execute(_input(NOW - timedelta(hours=24), NOW))

    assert len(inner.calls) == 1


def test_endpoints_do_not_share_entries() -> None:
    monotonic = FakeMonotonic()
    cache = TTLCache(ttl_seconds=60, monotonic=monotonic)
    overview, agent = RecordingQuery(), RecordingQuery()
    query = _input(NOW - timedelta(days=7), NOW)

    CachedMetricsQuery("overview", overview, cache, clock=lambda: NOW).execute(query)
    CachedMetricsQuery("agent", agent, cache, clock=lambda: NOW).execute(query)

    assert (len(overview.calls), len(agent.calls)) == (1, 1)


def test_errors_are_not_cached() -> None:
    inner, cache, cached = _cached(FakeMonotonic())

    for _ in range(2):
        with pytest.raises(ValueError):
            cached.execute(_input(NOW - timedelta(days=1), NOW, bad=["x"]))

    assert len(cache) == 0


def test_naive_datetimes_go_straight_to_the_use_case() -> None:
    inner, cache, cached = _cached(FakeMonotonic())

    cached.execute(MetricsQueryInput(from_=datetime(2026, 9, 1), to=datetime(2026, 9, 2)))

    assert len(cache) == 0 and len(inner.calls) == 1


def test_least_recently_used_entry_is_evicted_past_max_entries() -> None:
    inner, cache, cached = _cached(FakeMonotonic())
    queries = [_input(NOW - timedelta(days=d), NOW) for d in (1, 2, 3, 4)]

    for query in queries:
        cached.execute(query)
    cached.execute(queries[0])  # evicted -> recomputed

    assert len(cache) == 3
    assert len(inner.calls) == 5


def test_read_factories_serve_through_the_shared_cache() -> None:
    from src.application.use_cases.metrics.get_agent_metrics import GetAgentMetrics
    from src.application.use_cases.metrics.get_metrics_overview import (
        GetMetricsOverview,
    )
    from src.application.use_cases.metrics.get_technical_metrics import (
        GetTechnicalMetrics,
    )
    from src.infrastructure.entrypoint.api.factories import metrics_factory

    built = {
        "overview": (metrics_factory.get_metrics_overview_use_case(), GetMetricsOverview),
        "agent": (metrics_factory.get_agent_metrics_use_case(), GetAgentMetrics),
        "technical": (metrics_factory.get_technical_metrics_use_case(), GetTechnicalMetrics),
    }

    for endpoint, (use_case, inner_type) in built.items():
        assert isinstance(use_case, CachedMetricsQuery)
        assert use_case.endpoint == endpoint
        assert isinstance(use_case.inner, inner_type)
