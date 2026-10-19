"""Q4 equivalence: GET /metrics/overview and GET /metrics/agent numbers ==
a direct recomputation from the alert snapshots.

Random snapshots are written into an in-memory rollup repository through
the real writer path (alert_rollup_contribution.diff: first the decision
snapshot, then - for reviewed alerts - the review as a -old +new delta, so
negative increments are exercised). Random ranges + filters are then asked
through the real FastAPI routes; the oracle recomputes every number from
the snapshots themselves, without the contribution code.

The oracle includes an alert iff its local (date, hour) is covered by a
planned read (period_start..period_end, hours) - that is what the API
promises: beyond 90 days months are read whole and flagged `partial`. For
plans without a partial read, the test also checks that coverage is exactly
"hour slot starts in [from, min(to, now))"."""

from __future__ import annotations

import os
import random
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("GENAI_ENVIRONMENT", "test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dtos.metrics_dtos import MetricsQueryInput
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.metrics_rollup_port import RollupRow
from src.application.ports.operational_settings_port import OperationalSettings
from src.application.use_cases.metrics.alert_rollup_contribution import diff
from src.application.use_cases.metrics.get_agent_metrics import GetAgentMetrics
from src.application.use_cases.metrics.get_metrics_overview import GetMetricsOverview
from src.application.use_cases.metrics.range_planner import plan
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertResolutionMethod,
    AlertStatus,
    Mark,
)
from src.infrastructure.entrypoint.api.factories.metrics_factory import (
    get_agent_metrics_use_case,
    get_metrics_overview_use_case,
)
from src.infrastructure.entrypoint.api.routers import metrics_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

TZ = "America/Bogota"
ZONE = ZoneInfo(TZ)
NOW = datetime(2026, 10, 1, 15, 30, tzinfo=UTC)  # 10:30 Bogota

SEGMENTS = ["retail", "pyme", None]
CHANNELS = ["WEB", "APP", None]
SUBCHANNELS = ["PSE", "BREB", None]
TIERS = ["low", "mid", "high", "unknown"]
CONFIGS = ["cfg-1", "cfg-2", None]
STATUSES = [
    AlertStatus.CLOSED,
    AlertStatus.ESCALATED,
    AlertStatus.FAILED,
    AlertStatus.PROCESSING,
]
METHODS = [*AlertResolutionMethod, None]
FILTER_POOLS = {
    "segment": ["retail", "pyme", "unknown"],
    "channel": ["WEB", "APP", "unknown"],
    "subchannel": ["PSE", "BREB", "unknown"],
    "amount_tier": TIERS,
    "status": [s.value for s in STATUSES],
    "configuration_id": ["cfg-1", "cfg-2", "unknown"],
    "resolution_method": [m.value for m in AlertResolutionMethod] + ["unknown"],
}
RT_BUCKETS = [
    ("rt_lt_1m", 60),
    ("rt_1_5m", 300),
    ("rt_5_15m", 900),
    ("rt_15_30m", 1800),
    ("rt_gt_30m", None),
]
MAT_BUCKETS = [
    ("mat_lt_1d", 86400),
    ("mat_1_4d", 4 * 86400),
    ("mat_4_30d", 30 * 86400),
    ("mat_1_6mo", 183 * 86400),
    ("mat_gt_6mo", None),
]


# --- fakes ----------------------------------------------------------------------


class InMemoryMetricsRollupRepository:
    """Stores what the writer's deltas add up to, keyed like DynamoDB rows."""

    def __init__(self) -> None:
        self.rows: dict = defaultdict(lambda: defaultdict(lambda: [0.0] * 24))

    def write(self, deltas) -> None:
        for delta in deltas:
            for measure, value in delta.measures.items():
                self.rows[delta.key][measure][delta.hour] += value

    def apply(self, deltas, alert_guard) -> None:
        self.write(deltas)

    def query(self, data_type, level, periods, filters=None):
        wanted = set(periods)
        result = []
        for key, measures in self.rows.items():
            if (
                key.data_type != data_type
                or key.level != level
                or key.period not in wanted
            ):
                continue
            if any(
                key.dimension(name) not in values
                for name, values in (filters or {}).items()
            ):
                continue
            result.append(
                RollupRow(key=key, measures={m: list(s) for m, s in measures.items()})
            )
        return result


class InMemoryOperationalSettingsRepository:
    def __init__(self, settings: OperationalSettings) -> None:
        self.settings = settings

    def get(self) -> OperationalSettings:
        return self.settings


# --- random data ------------------------------------------------------------------


def _random_alert(rng: random.Random):
    created_at = NOW - timedelta(seconds=rng.randint(0, 500 * 86400))
    method = rng.choice(METHODS)
    mark = rng.choice([Mark.FRAUD, Mark.NO_FRAUD, Mark.PENDING])
    decided = mark != Mark.PENDING
    rt = rng.choice([30, 200, 600, 1500, 4000, 0]) + rng.random() if decided else None
    marked_at = created_at + timedelta(seconds=rt) if decided else None
    amount = rng.choice([None, round(rng.uniform(1_000, 5_000_000), 2)])
    version = rng.choice([None, 1, 2])
    base = AlertMetricsSnapshot(
        origin=rng.choice(["manual", "simulator", None]),
        segment=rng.choice(SEGMENTS),
        channel=rng.choice(CHANNELS),
        subchannel=rng.choice(SUBCHANNELS),
        amount=amount,
        amount_tier=rng.choice(TIERS),
        schema_version=version,
        configuration_id=rng.choice(CONFIGS),
        resolution_method=method,
        mark=mark,
        fraud_label=mark,
        marked_at=marked_at,
        resolution_time_seconds=rt,
        status=rng.choice(STATUSES),
        snapshot_version=1,
    )
    final = base
    if rng.random() < 0.4:
        label = rng.choice([Mark.FRAUD, Mark.NO_FRAUD])
        reviewed_at = (marked_at or created_at) + timedelta(
            seconds=rng.choice([3600, 3 * 86400, 20 * 86400, 90 * 86400, 300 * 86400])
        )
        final = replace(
            base,
            fraud_label=label,
            fraud_reviewed_at=reviewed_at,
            fraud_review_count=rng.randint(1, 3),
            snapshot_version=2,
        )
    return created_at, base, final


def _populate(rng: random.Random, n: int):
    repo = InMemoryMetricsRollupRepository()
    alerts = []
    for _ in range(n):
        created_at, base, final = _random_alert(rng)
        repo.write(diff(None, base, created_at, NOW, TZ))
        if final is not base:
            repo.write(diff(base, final, created_at, NOW, TZ))
        alerts.append((created_at, final))
    return repo, alerts


def _random_query(rng: random.Random):
    # Half inside the 90-day day-row window (exact hour slots), half anywhere.
    days_back = rng.randint(0, 89) if rng.random() < 0.5 else rng.randint(0, 560)
    start = NOW - timedelta(days=days_back, minutes=rng.randint(0, 1439))
    span = rng.choice(
        [
            timedelta(hours=rng.randint(1, 30)),
            timedelta(days=rng.randint(1, 45)),
            timedelta(days=rng.randint(30, 420)),
        ]
    )
    filters = {}
    for name in rng.sample(list(FILTER_POOLS), rng.randint(0, 3)):
        filters[name] = rng.sample(FILTER_POOLS[name], rng.randint(1, 2))
    return start, start + span, filters


# --- oracle -------------------------------------------------------------------------


def _dim(value) -> str:
    if value is None or value == "":
        return "unknown"
    return str(getattr(value, "value", value))


def _bucket(buckets, seconds):
    for name, upper in buckets:
        if upper is None or seconds < upper:
            return name
    return buckets[-1][0]


def _selected(alerts, reads, filters):
    covered = []
    for created_at, s in alerts:
        local = created_at.astimezone(ZONE)
        if not any(
            r.period_start <= local.date() <= r.period_end and local.hour in r.hours
            for r in reads
        ):
            continue
        if any(
            _dim(getattr(s, name)) not in values for name, values in filters.items()
        ):
            continue
        covered.append((created_at, s))
    return covered


def _quality(group):
    q = defaultdict(float)
    for _, s in group:
        if s.mark != Mark.PENDING:
            q["decided"] += 1
        pair = (s.mark, s.fraud_label)
        if pair == (Mark.FRAUD, Mark.FRAUD):
            q["true_positives"] += 1
            q["true_positive_amount_sum"] += s.amount or 0
        if pair == (Mark.NO_FRAUD, Mark.NO_FRAUD):
            q["true_negatives"] += 1
        if pair == (Mark.FRAUD, Mark.NO_FRAUD):
            q["false_positives"] += 1
            q["false_positive_amount_sum"] += s.amount or 0
        if pair == (Mark.NO_FRAUD, Mark.FRAUD):
            q["undetected_fraud"] += 1
            q["undetected_fraud_amount_sum"] += s.amount or 0
        if s.fraud_reviewed_at is not None:
            q["reviewed"] += 1
            q["review_events"] += s.fraud_review_count
            if s.mark != Mark.PENDING:
                q[
                    "reviewed_changed"
                    if s.fraud_label != s.mark
                    else "reviewed_confirmed"
                ] += 1
            if s.marked_at is not None:
                q[
                    _bucket(
                        MAT_BUCKETS, (s.fraud_reviewed_at - s.marked_at).total_seconds()
                    )
                ] += 1
    q["pending"] = len(group) - q["decided"]
    return q


def _rt(group):
    r = defaultdict(float)
    for _, s in group:
        if s.resolution_time_seconds is not None:
            r["count"] += 1
            r["sum_seconds"] += s.resolution_time_seconds
            r[_bucket(RT_BUCKETS, s.resolution_time_seconds)] += 1
    r["within_sla_count"] = r["rt_lt_1m"] + r["rt_1_5m"]
    return r


def _assert_quality(actual, group):
    q = _quality(group)
    for name in (
        "decided",
        "pending",
        "true_positives",
        "true_negatives",
        "false_positives",
        "undetected_fraud",
        "reviewed",
        "reviewed_changed",
        "reviewed_confirmed",
        "review_events",
    ):
        assert actual[name] == q[name], name
    for name in (
        "true_positive_amount_sum",
        "false_positive_amount_sum",
        "undetected_fraud_amount_sum",
    ):
        assert actual[name] == pytest.approx(q[name], abs=1e-3), name
    assert {b["bucket"]: b["count"] for b in actual["maturation_histogram"]} == {
        name: q[name] for name, _ in MAT_BUCKETS
    }


def _assert_rt(actual, group):
    r = _rt(group)
    assert actual["count"] == r["count"]
    assert actual["sum_seconds"] == pytest.approx(r["sum_seconds"], abs=1e-3)
    assert actual["within_sla_count"] == r["within_sla_count"]
    assert {b["bucket"]: b["count"] for b in actual["histogram"]} == {
        name: r[name] for name, _ in RT_BUCKETS
    }


# --- harness ----------------------------------------------------------------------


def _client(repo, role=LocalRole.MANAGER) -> TestClient:
    now = datetime.now(UTC)
    user = LocalUser(
        id=uuid4(),
        email="m@aria.test",
        name="M",
        password_hash="x",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    app = FastAPI()
    app.include_router(metrics_router.router, prefix="/api/v0")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_metrics_overview_use_case] = (
        lambda: GetMetricsOverview(repo, TZ, clock=lambda: NOW)
    )
    app.dependency_overrides[get_agent_metrics_use_case] = lambda: GetAgentMetrics(
        repo, TZ, clock=lambda: NOW
    )
    return TestClient(app)


def _params(from_, to, filters):
    params = [("from", from_.isoformat()), ("to", to.isoformat())]
    for name, values in filters.items():
        params.extend((name, value) for value in values)
    return params


def test_metrics_read_maturity_thresholds_from_operational_settings() -> None:
    settings = InMemoryOperationalSettingsRepository(
        OperationalSettings(maturing_days=0, stable_months=0)
    )
    use_case = GetMetricsOverview(
        InMemoryMetricsRollupRepository(),
        TZ,
        clock=lambda: NOW,
        operational_settings_repository=settings,
    )
    query = MetricsQueryInput(
        from_=datetime(2026, 10, 1, 12, tzinfo=UTC),
        to=datetime(2026, 10, 1, 15, tzinfo=UTC),
    )

    first = use_case.execute(query)
    assert all(period.maturation == "stable" for period in first.periods)

    settings.settings = OperationalSettings(maturing_days=4, stable_months=6)
    second = use_case.execute(query)
    assert all(period.maturation == "maturing" for period in second.periods)


@pytest.mark.parametrize("seed", range(6))
def test_endpoint_numbers_equal_a_direct_recomputation_from_the_snapshots(
    seed: int,
) -> None:
    rng = random.Random(seed)
    repo, alerts = _populate(rng, 400)
    client = _client(repo)

    for _ in range(12):
        from_, to, filters = _random_query(rng)
        reads = plan(from_, to, NOW, TZ)
        selected = _selected(alerts, reads, filters)

        if reads and not any(r.partial for r in reads):
            in_slots = []
            for created_at, s in alerts:
                slot = created_at.replace(minute=0, second=0, microsecond=0)
                if from_ <= slot < min(to, NOW) and not any(
                    _dim(getattr(s, n)) not in v for n, v in filters.items()
                ):
                    in_slots.append((created_at, s))
            assert len(in_slots) == len(selected)

        overview = client.get(
            "/api/v0/metrics/overview", params=_params(from_, to, filters)
        )
        assert overview.status_code == 200, overview.text
        body = overview.json()

        assert body["totals"]["alerts"] == len(selected)
        assert body["totals"]["amount_sum"] == pytest.approx(
            sum(s.amount or 0 for _, s in selected), abs=1e-3
        )
        assert body["totals"]["amount_count"] == sum(
            1 for _, s in selected if s.amount is not None
        )
        _assert_quality(body["fraud_quality"], selected)
        _assert_rt(body["resolution_time"], selected)

        hourly = defaultdict(int)
        for created_at, _ in selected:
            hourly[created_at.astimezone(ZONE).hour] += 1
        assert [slot["alerts"] for slot in body["hourly_profile"]] == [
            hourly[h] for h in range(24)
        ]

        for name, buckets in body["distributions"].items():
            expected = defaultdict(int)
            for _, s in selected:
                expected[_dim(getattr(s, name))] += 1
            assert {b["value"]: b["alerts"] for b in buckets} == dict(expected), name
            for b in buckets:
                group = [
                    (c, s) for c, s in selected if _dim(getattr(s, name)) == b["value"]
                ]
                q = _quality(group)
                assert (b["false_positives"], b["undetected_fraud"]) == (
                    q["false_positives"],
                    q["undetected_fraud"],
                )

        funnel = {b["value"]: b["alerts"] for b in body["funnel_by_status"]}
        for status in AlertStatus:
            assert funnel[status.value] == sum(
                1 for _, s in selected if s.status == status
            )

        assert [p["period"] for p in body["periods"]] == [r.period for r in reads]
        for period, read in zip(body["periods"], reads):
            in_period = _selected(selected, [read], {})
            assert period["alerts"] == len(in_period)
            assert period["false_positives"] == _quality(in_period)["false_positives"]
            assert period["maturation"] == read.maturation.value
            assert period["partial"] == read.partial

        versions = sorted({_dim(s.schema_version) for _, s in selected})
        assert body["range"]["schema_versions"] == versions
        codes = {w["code"] for w in body["warnings"]}
        assert ("schema_changed" in codes) == (len(versions) > 1)
        assert ("partial_period" in codes) == any(r.partial for r in reads)

        agent = client.get("/api/v0/metrics/agent", params=_params(from_, to, filters))
        assert agent.status_code == 200, agent.text
        agent_body = agent.json()
        assert agent_body["totals"]["alerts"] == len(selected)
        assert agent_body["recommendations"]["available"] is False
        for stats in agent_body["by_resolution_method"]:
            group = [
                (c, s)
                for c, s in selected
                if _dim(s.resolution_method) == stats["resolution_method"]
            ]
            assert stats["alerts"] == len(group)
            assert stats["fraud_marks"] == sum(
                1 for _, s in group if s.mark == Mark.FRAUD
            )
            assert stats["no_fraud_marks"] == sum(
                1 for _, s in group if s.mark == Mark.NO_FRAUD
            )
            _assert_quality(stats["fraud_quality"], group)
            _assert_rt(stats["resolution_time"], group)


def test_metrics_routes_check_the_dashboard_and_monitor_permissions() -> None:
    repo = InMemoryMetricsRollupRepository()
    # data_analyst: monitor yes, dashboard no.
    client = _client(repo, role=LocalRole.DATA_ANALYST)
    assert client.get("/api/v0/metrics/overview").status_code == 403
    assert client.get("/api/v0/metrics/agent").status_code == 200
    # fraud_analyst: neither.
    client = _client(repo, role=LocalRole.FRAUD_ANALYST)
    assert client.get("/api/v0/metrics/agent").status_code == 403


def test_inverted_range_and_naive_datetimes() -> None:
    client = _client(InMemoryMetricsRollupRepository())
    bad = client.get(
        "/api/v0/metrics/overview",
        params={"from": "2026-09-30T00:00:00+00:00", "to": "2026-09-29T00:00:00+00:00"},
    )
    assert bad.status_code == 422
    # No offset = operations timezone (Bogota).
    ok = client.get(
        "/api/v0/metrics/overview",
        params={"from": "2026-09-30T00:00:00", "to": "2026-10-01T00:00:00"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["range"]["from"].startswith("2026-09-30T00:00:00-05:00")
    assert [p["period"] for p in body["periods"]] == ["2026-09-30"]
    assert body["periods"][0]["hours"] == list(range(24))
