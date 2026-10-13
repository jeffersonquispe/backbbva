"""Metrics query benchmark (A4) - dev tool:

    make metrics-query-bench DYNAMO_PORT=8012 [RUNS=15]
    python -m src.infrastructure.entrypoint.api.metrics_query_bench --runs 15

Times GET /metrics/overview, /metrics/agent and /metrics/technical
in-process, the way the router serves them: the API factory's use case
(real DynamoMetricsRollupRepository, real clock) + the response model
validation + JSON serialization - minus HTTP and auth. Ranges 24h, 7d,
30d, 90d and 1y back from now, each without and with filters. Reports
p50/p95/max per case, DynamoDB Query calls, items and bytes read per
request, and the ConsumedCapacity DynamoDB reports.

`--cached` goes through the factories' 60 s per-query cache
(metrics_query_cache.CachedMetricsQuery) to measure warm hits; the first
(warm-up) run of each case is the cold miss."""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

RANGES = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
}
FILTER_SETS: dict[str, dict[str, list[str]]] = {
    "none": {},
    "channel+segment": {"channel": ["APP"], "segment": ["retail"]},
    "tier+method": {"amount_tier": ["lt_1m"], "resolution_method": ["aria", "analyst"]},
}

_tally = threading.local()


def _install_hooks(client: Any) -> None:
    def add_rcc(params: dict[str, Any], **_: Any) -> None:
        params.setdefault("ReturnConsumedCapacity", "TOTAL")

    def record(http_response: Any, parsed: dict[str, Any], **_: Any) -> None:
        counter = getattr(_tally, "counter", None)
        if counter is None or not isinstance(parsed, dict):
            return
        counter["queries"] += 1
        counter["items"] += int(parsed.get("Count", 0))
        counter["rcu"] += float(
            (parsed.get("ConsumedCapacity") or {}).get("CapacityUnits", 0)
        )
        counter["bytes"] += len(getattr(http_response, "content", b"") or b"")

    client.meta.events.register("provide-client-params.dynamodb.Query", add_rcc)
    client.meta.events.register("after-call.dynamodb.Query", record)


def _endpoints():
    from src.infrastructure.entrypoint.api.factories.metrics_factory import (
        get_agent_metrics_use_case,
        get_metrics_overview_use_case,
        get_technical_metrics_use_case,
    )
    from src.infrastructure.entrypoint.api.schemas import (
        AgentMetricsResponse,
        MetricsOverviewResponse,
        TechnicalMetricsResponse,
    )

    return {
        "overview": (get_metrics_overview_use_case, MetricsOverviewResponse),
        "agent": (get_agent_metrics_use_case, AgentMetricsResponse),
        "technical": (get_technical_metrics_use_case, TechnicalMetricsResponse),
    }


def _serve(factory, response_model, from_, to, filters, cached: bool) -> str:
    """What the router does for one request, returned as the JSON body.
    The factories return the use case wrapped in the 60 s query cache
    (CachedMetricsQuery); without --cached the wrapped use case is called
    directly, so every run hits DynamoDB."""
    from src.application.dtos.metrics_dtos import MetricsQueryInput

    use_case = factory()
    if not cached:
        use_case = getattr(use_case, "inner", use_case)
    output = use_case.execute(
        MetricsQueryInput(
            from_=from_, to=to, filters={k: list(v) for k, v in filters.items()}
        )
    )
    return response_model.model_validate(asdict(output)).model_dump_json()


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--endpoints", default="overview,agent,technical")
    parser.add_argument("--ranges", default=",".join(RANGES))
    parser.add_argument("--filters", default=",".join(FILTER_SETS))
    parser.add_argument("--cached", action="store_true")
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args(argv)

    from src.infrastructure.persistence.database.dynamodb.client import (
        get_dynamodb_resource,
    )

    _install_hooks(get_dynamodb_resource().meta.client)
    endpoints = _endpoints()
    results = []
    print(
        f"{'endpoint':<10}{'range':<6}{'filters':<17}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}"
        f"{'queries':>9}{'items':>9}{'MB':>7}{'RCU':>8}{'resp KB':>9}"
    )
    for name in args.endpoints.split(","):
        factory, response_model = endpoints[name]
        for range_name in args.ranges.split(","):
            for filter_name in args.filters.split(","):
                filters = FILTER_SETS[filter_name]
                timings: list[float] = []
                counter: Counter = Counter()
                body = ""
                for run in range(args.warmup + args.runs):
                    to = datetime.now(UTC)
                    # Same range for every run of a case (cache key stable
                    # within the minute, like a dashboard refresh).
                    to = to.replace(second=0, microsecond=0)
                    from_ = to - RANGES[range_name]
                    _tally.counter = Counter()
                    started = time.perf_counter()
                    body = _serve(
                        factory, response_model, from_, to, filters, args.cached
                    )
                    elapsed = (time.perf_counter() - started) * 1000
                    if run >= args.warmup:
                        timings.append(elapsed)
                        counter.update(_tally.counter)
                    _tally.counter = None
                n = len(timings)
                row = {
                    "endpoint": name,
                    "range": range_name,
                    "filters": filter_name,
                    "runs": n,
                    "p50_ms": round(statistics.median(timings), 1),
                    "p95_ms": round(_percentile(timings, 0.95), 1),
                    "max_ms": round(max(timings), 1),
                    "queries": round(counter["queries"] / n, 1),
                    "items": round(counter["items"] / n),
                    "mb_read": round(counter["bytes"] / n / 1e6, 2),
                    "rcu": round(counter["rcu"] / n, 1),
                    "response_kb": round(len(body) / 1024, 1),
                }
                results.append(row)
                print(
                    f"{name:<10}{range_name:<6}{filter_name:<17}{row['p50_ms']:>9}{row['p95_ms']:>9}"
                    f"{row['max_ms']:>9}{row['queries']:>9}{row['items']:>9}{row['mb_read']:>7}"
                    f"{row['rcu']:>8}{row['response_kb']:>9}",
                    flush=True,
                )
    if args.json_path:
        with open(args.json_path, "w") as fh:
            json.dump(results, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
