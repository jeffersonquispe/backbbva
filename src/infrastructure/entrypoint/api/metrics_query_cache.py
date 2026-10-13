"""Short per-query cache for GET /metrics/overview|agent|technical (A4).

A dashboard refresh re-asks the same range every few seconds, and a 90-day
range reads ~90 DynamoDB partitions. The rollups are additive counters
updated live, so serving an answer up to TTL_SECONDS old is acceptable
(decision A4: 60 s) and turns repeated reads into a dict lookup.

Infrastructure only - the use cases stay uncached. The factories in
factories/metrics_factory.py wrap each read use case in CachedMetricsQuery;
a test that overrides a factory with its own use case bypasses the cache.

Key = (endpoint, effective range snapped to the hour slots the range
planner reads, filters normalized). The planner reads a slot iff its start
lies in [from, min(to, now)), so two ranges with the same ceil-to-hour
bounds read exactly the same slots: e.g. a dashboard asking "last 24 h" at
10:05:12 and 10:05:47 shares one entry. The cached output's `range` is
re-stamped with each caller's own from/to."""
from __future__ import annotations

import dataclasses
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Generic, Protocol, TypeVar

from src.application.dtos.metrics_dtos import MetricsQueryInput
from src.application.use_cases.metrics.alert_metrics_reader import DEFAULT_RANGE

TTL_SECONDS = 60.0
MAX_ENTRIES = 512

T = TypeVar("T")


class TTLCache:
    """Thread-safe dict with per-entry expiry and LRU eviction."""

    def __init__(
        self,
        ttl_seconds: float = TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._monotonic = monotonic
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_compute(self, key: Hashable, compute: Callable[[], T]) -> T:
        now = self._monotonic()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and hit[0] > now:
                self._entries.move_to_end(key)
                return hit[1]
        # Computed outside the lock: a slow DynamoDB read must not block
        # other keys. Two concurrent misses on one key both compute; the
        # later one wins - harmless for a read-only cache.
        value = compute()
        with self._lock:
            self._entries[key] = (self._monotonic() + self._ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


def _ceil_hour(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    floor = value.replace(minute=0, second=0, microsecond=0)
    return floor if floor == value else floor + timedelta(hours=1)


def query_cache_key(
    endpoint: str, input: MetricsQueryInput, now: datetime
) -> tuple[Hashable, datetime, datetime]:
    """(key, effective from, effective to) - the defaults resolved as the
    use cases resolve them (to = now, from = to - 24 h)."""
    to = input.to or now
    from_ = input.from_ or (to - DEFAULT_RANGE)
    filters = tuple(
        sorted(
            (name, tuple(sorted({str(v).strip() for v in values if str(v).strip()})))
            for name, values in (input.filters or {}).items()
            if values
        )
    )
    key = (endpoint, _ceil_hour(from_), _ceil_hour(min(to, now)), filters)
    return key, from_, to


class _MetricsQuery(Protocol[T]):
    def execute(self, input: MetricsQueryInput) -> T: ...


class CachedMetricsQuery(Generic[T]):
    """Same execute() as the wrapped read use case, served from `cache`
    for TTL seconds per normalized query. Errors (ValueError -> 422) are
    never cached."""

    def __init__(
        self,
        endpoint: str,
        inner: _MetricsQuery[T],
        cache: TTLCache,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.endpoint = endpoint
        self.inner = inner
        self._cache = cache
        self._clock = clock

    def execute(self, input: MetricsQueryInput) -> T:
        now = self._clock()
        for value in (input.from_, input.to):
            if value is not None and value.tzinfo is None:
                return self.inner.execute(input)  # let the use case reject it
        key, from_, to = query_cache_key(self.endpoint, input, now)
        output = self._cache.get_or_compute(key, lambda: self.inner.execute(input))
        stamped_range = dataclasses.replace(output.range, from_=from_, to=to)
        return dataclasses.replace(output, range=stamped_range)


@lru_cache
def get_metrics_query_cache() -> TTLCache:
    return TTLCache()
