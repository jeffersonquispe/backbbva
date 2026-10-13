"""Synthetic metrics load (Q3) - dev/benchmark tool, never run against a
shared or production DynamoDB:

    make metrics-synthetic-load DAYS=90 PER_DAY=1500 LOADTEST_DYNAMO_PORT=8012
    python -m src.infrastructure.entrypoint.worker.metrics_synthetic_load \
        --days 90 --per-day 1500 [--tech-sample 0.1] [--workers 1] [--seed 7]

Driving the real simulator + LLM workflow for ~135k alerts is not feasible
locally, so this generates realistic alerts directly and pushes every event
of their life through the REAL writers, with a fake clock set to each
event's time:

- RecordAlertMetricsEvent: CREATED -> PRE_PROCESSED -> WORKFLOW_FINISHED ->
  (ANALYST_RESOLVED | VOICEBOT_COMPLETED) -> FRAUD_REVIEWED (~98 % of the
  reviews within 4 days of the decision, ~2 % between 4 days and 6 months;
  reviews later than now are dropped - they have not happened yet).
- RecordWorkflowStepMetrics for a sample of the alerts (--tech-sample),
  with synthetic step records (durations, tokens, research calls) held in
  an in-memory step repository.

Alerts and rollups are written with the real Dynamo repositories, so the
transactions, item sizes and capacity units are the real ones. The amount
tier sets are held by an in-memory settings repository and can change during
the run; each alert keeps the tier classified at arrival.

There is no table prefix in this repo (table names are constants), so point
it at a THROWAWAY DynamoDB Local (the Make target defaults to port 8012),
never at the stack's 8002: it creates `alerts` and `metrics_rollups` there.
Every DynamoDB call's ConsumedCapacity is tallied per event type and the
run ends with rows/items/bytes per level and throughput."""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import random
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from botocore.exceptions import ClientError

TZ_NAME = "America/Bogota"
TZ = ZoneInfo(TZ_NAME)

# --- distributions ------------------------------------------------------------

# Bogota hour-of-day weights: quiet night, morning ramp, evening peak.
HOUR_WEIGHTS = [
    1,
    1,
    1,
    1,
    1,
    2,
    3,
    5,
    7,
    8,
    8,
    8,
    9,
    8,
    8,
    8,
    8,
    9,
    10,
    10,
    9,
    7,
    4,
    2,
]
ORIGINS = [("production", 0.90), ("simulator", 0.08), ("manual", 0.02)]
CHANNELS: list[tuple[str, float, list[tuple[str, float]]]] = [
    (
        "APP",
        0.48,
        [("PSE", 0.35), ("TRANSFER", 0.40), ("BILLPAY", 0.15), ("camel", 0.10)],
    ),
    ("WEB", 0.22, [("PSE", 0.50), ("TRANSFER", 0.35), ("BILLPAY", 0.15)]),
    ("POS", 0.18, [("ECOM", 0.70), ("PRESENTIAL", 0.30)]),
    ("ATM", 0.07, [("WITHDRAWAL", 1.0)]),
    ("GL", 0.05, [("BRANCH", 0.6), ("CALLCENTER", 0.4)]),
]
SEGMENTS = [
    ("retail", 0.62),
    ("premium", 0.14),
    ("pyme", 0.12),
    ("empresas", 0.06),
    ("private_banking", 0.03),
    (None, 0.03),
]
# executed_action, final status for the run, probability.
WORKFLOW_OUTCOMES = [
    ("none", "CLOSED", 0.50),
    ("discarded", "CLOSED", 0.10),
    ("block", "CLOSED", 0.08),
    ("voicebot", "CLOSED", 0.14),
    ("scale_to_analyst", "ESCALATED", 0.13),
    ("bidi", "CLOSED", 0.03),
    (None, "FAILED", 0.02),
]
ANALYST_DECISIONS = [("pass", 0.72), ("block", 0.25), ("bidi", 0.03)]
VOICEBOT_OUTCOMES = [
    ("customer_recognized", 0.62),
    ("customer_not_recognized", 0.14),
    ("no_answer", 0.18),
    ("busy", 0.06),
]
CONFIGURATION_IDS = ("cfg-2026-06", "cfg-2026-08")
# Share of decided alerts the fraud team ever reviews, and of those, how
# many flip the label / get a second review.
REVIEW_PROBABILITY = 0.35
REVIEW_FLIP_PROBABILITY = 0.08
SECOND_REVIEW_PROBABILITY = 0.03

TIERS_V1 = [  # COP
    ("lt_1m", "< 1M", 0, 1_000_000),
    ("1m_3m", "1M - 3M", 1_000_000, 3_000_000),
    ("gt_3m", "> 3M", 3_000_000, None),
]

LLM_STEP_MODELS = {
    "detector": "gpt-4.1-mini",
    "detector_adversarial": "gpt-4.1-mini",
    "classification": "gpt-4.1-mini",
    "adversarial": "gpt-4.1-mini",
    "analyst": "gpt-4.1",
    "executor": "gpt-4.1-mini",
}
# step -> (median seconds, input tokens range, output tokens range)
STEP_PROFILE: dict[str, tuple[float, tuple[int, int], tuple[int, int]]] = {
    "pre_process": (1.2, (0, 0), (0, 0)),
    "deterministic": (0.2, (0, 0), (0, 0)),
    "profiling": (2.5, (0, 0), (0, 0)),
    "detector": (4.0, (1500, 3500), (150, 400)),
    "detector_adversarial": (5.0, (2000, 4000), (200, 500)),
    "classification": (6.0, (3000, 6000), (300, 700)),
    "adversarial": (6.0, (3000, 6000), (300, 700)),
    "analyst": (25.0, (8000, 22000), (800, 2000)),
    "executor": (3.0, (1500, 3000), (100, 300)),
    "post_process": (0.5, (0, 0), (0, 0)),
}
STEPS = tuple(STEP_PROFILE)


def _pick(rng: random.Random, options: list[tuple[Any, float]]) -> Any:
    return rng.choices([o[0] for o in options], weights=[o[1] for o in options])[0]


# --- capacity tally -------------------------------------------------------------


@dataclass
class Tally:
    """ConsumedCapacity per (tag, operation) as DynamoDB reports it, plus a
    size-based WCU model for a sample of the transactions (DynamoDB Local
    only reports the FIRST item of a TransactWriteItems, so its number for
    transactions is not usable)."""

    calls: Counter = field(default_factory=Counter)
    items: Counter = field(default_factory=Counter)
    units: Counter = field(default_factory=Counter)
    # Sampled transactions: count, modeled WCU, items > 1 KB.
    probed: Counter = field(default_factory=Counter)
    modeled_wcu: Counter = field(default_factory=Counter)
    probed_items: Counter = field(default_factory=Counter)
    probed_items_over_1kb: Counter = field(default_factory=Counter)
    conflicts: int = 0


_current = threading.local()
# Alerts table GSIs with ALL projection (EventIdIdx, CreatedDayIdx): an
# update of the alert item is also written to both. StatusIdx is KEYS_ONLY
# and status is not changed by the metrics writer.
ALERT_ALL_PROJECTION_GSIS = 2


def _kb(size: int) -> int:
    return max(1, math.ceil(size / 1024))


def install_capacity_hooks(client: Any, tally: Tally, probe_rate: float) -> None:
    """Every call: ReturnConsumedCapacity + tally. A `probe_rate` share of
    the transactions is re-read after commit to model their real cost:
    2 WCU per KB per item (transactional writes cost double; an ADD only
    grows a row, so the size after = max(before, after)), plus the alert's
    two ALL-projection GSI writes (1 WCU per KB each)."""
    # `client` is the boto3 resource's client: its calls take and return
    # plain Python values (the resource's (de)serialization hooks).
    operations = ("TransactWriteItems", "GetItem", "PutItem", "Query", "UpdateItem")
    rng = random.Random(1)

    def add_rcc(params: dict[str, Any], **_: Any) -> None:
        if getattr(_current, "probing", False):
            return
        params.setdefault("ReturnConsumedCapacity", "TOTAL")
        if "TransactItems" in params:
            _current.tx = params["TransactItems"]

    def probe(tag: str) -> None:
        _current.probing = True
        try:
            wcu = 0
            for entry in _current.tx:
                op = entry.get("Update") or entry.get("Put")
                key = op.get("Key") or {
                    k: op["Item"][k] for k in ("pk", "sk") if k in op["Item"]
                }
                item = (
                    client.get_item(
                        TableName=op["TableName"], Key=key, ConsistentRead=True
                    ).get("Item")
                    or {}
                )
                size = item_size(item)
                wcu += 2 * _kb(size)
                if op["TableName"] == "alerts":
                    wcu += ALERT_ALL_PROJECTION_GSIS * _kb(size)
                tally.probed_items[tag] += 1
                if size > 1024:
                    tally.probed_items_over_1kb[tag] += 1
            tally.probed[tag] += 1
            tally.modeled_wcu[tag] += wcu
        finally:
            _current.probing = False

    def record(
        http_response: Any, parsed: dict[str, Any], model: Any, **_: Any
    ) -> None:
        if getattr(_current, "probing", False):
            return
        if not isinstance(parsed, dict) or parsed.get("Error", {}).get("Code"):
            return
        tag = getattr(_current, "tag", "other")
        key = f"{tag}:{model.name}"
        consumed = parsed.get("ConsumedCapacity")
        units = 0.0
        if isinstance(consumed, list):
            units = sum(float(c.get("CapacityUnits", 0)) for c in consumed)
        elif isinstance(consumed, dict):
            units = float(consumed.get("CapacityUnits", 0))
        tally.calls[key] += 1
        tally.units[key] += units
        if model.name == "TransactWriteItems":
            tally.items[key] += len(_current.tx)
            if rng.random() < probe_rate:
                probe(tag)

    for op in operations:
        client.meta.events.register(f"provide-client-params.dynamodb.{op}", add_rcc)
        client.meta.events.register(f"after-call.dynamodb.{op}", record)


# --- in-memory collaborators ------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


class TierSwitchingSettings:
    """OperationalSettingsRepository fake: no amount tiers (version 0)
    before `change_at`, TIERS_V1 (version 1) from then on."""

    def __init__(self, clock: Clock, change_at: datetime) -> None:
        from src.application.ports.operational_settings_port import (
            AmountTier,
            OperationalSettings,
        )

        self._clock = clock
        self._change_at = change_at
        self._before = OperationalSettings()
        self._after = OperationalSettings(
            amount_tiers=[
                AmountTier(code, label, lower, upper)
                for code, label, lower, upper in TIERS_V1
            ],
        )

    def get(self):
        return self._after if self._clock() >= self._change_at else self._before


class InMemoryStepRepository:
    def __init__(self) -> None:
        self.by_workflow: dict[uuid.UUID, list[Any]] = {}

    def list_by_workflow(self, workflow_execution_id: uuid.UUID) -> list[Any]:
        return list(self.by_workflow.get(workflow_execution_id, []))


# --- one alert's life ---------------------------------------------------------------


@dataclass
class PlannedEvent:
    at: datetime
    tag: str
    input: Any  # RecordAlertMetricsEventInput, or "steps" marker


def _amount(rng: random.Random) -> float:
    # Lognormal COP, median ~350k, long tail into tens of millions.
    return round(min(math.exp(rng.gauss(math.log(350_000), 1.3)), 250_000_000), 2)


def _created_at(rng: random.Random, day: date) -> datetime:
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
    local = datetime(
        day.year,
        day.month,
        day.day,
        hour,
        rng.randrange(60),
        rng.randrange(60),
        tzinfo=TZ,
    )
    return local.astimezone(UTC)


def _steps_for(
    rng: random.Random, workflow_id: uuid.UUID, start: datetime, action: str | None
) -> tuple[list[Any], datetime]:
    from src.application.ports.workflow_port import (
        WorkflowStepExecutionRecord,
        WorkflowStepStatus,
    )

    if action == "discarded":
        names = ["pre_process", "deterministic", "post_process"]
    else:
        names = list(STEPS)
        if rng.random() < 0.06:  # adversarial feedback loop re-runs
            i = names.index("adversarial") + 1
            names[i:i] = ["classification", "adversarial"]
    fail_at = rng.randrange(len(names)) if action is None else None
    records = []
    t = start
    for index, name in enumerate(names):
        median, tin, tout = STEP_PROFILE[name]
        seconds = max(0.05, median * math.exp(rng.gauss(0, 0.5)))
        failed = index == fail_at
        output: dict[str, Any] = {}
        if tin[1]:
            output["input_tokens"] = 0 if failed else rng.randint(*tin)
            output["output_tokens"] = 0 if failed else rng.randint(*tout)
        if name == "analyst" and not failed:
            output["research_delegations"] = [
                {
                    "source": rng.choice(["vector_store", "transaction_history"]),
                    "status": "failed" if (r := rng.random()) < 0.04 else "executed",
                    "error": ("timeout after 20s" if r < 0.02 else "backend error")
                    if r < 0.04
                    else None,
                }
                for _ in range(rng.randint(1, 3))
            ]
        finished = t + timedelta(seconds=seconds)
        records.append(
            WorkflowStepExecutionRecord(
                id=uuid.uuid4(),
                workflow_execution_id=workflow_id,
                step_name=name,
                status=WorkflowStepStatus.FAILED
                if failed
                else WorkflowStepStatus.SUCCEEDED,
                attempt=1,
                input=None,
                output=output,
                error="synthetic failure" if failed else None,
                started_at=t,
                finished_at=finished,
                created_at=t,
                updated_at=finished,
            )
        )
        t = finished
        if failed:
            break
    return records, t


def plan_alert(rng: random.Random, created_at: datetime, now: datetime, tech: bool):
    """(AlertRecord, events in time order, step records or None)."""
    from src.application.dtos.alert_metrics_dtos import (
        AlertMetricsEventType as E,
    )
    from src.application.dtos.alert_metrics_dtos import (
        RecordAlertMetricsEventInput as I,
    )
    from src.application.ports.alert_port import AlertRecord, AlertStatus, Mark

    alert_id = uuid.uuid4()
    channel_row = rng.choices(CHANNELS, weights=[c[1] for c in CHANNELS])[0]
    channel, subchannel = channel_row[0], _pick(rng, channel_row[2])
    payload = {
        "channel": channel,
        "integrationPoint": subchannel,
        "amount": {"baseValue": _amount(rng), "currency": "COP"},
        # Filler so the stored alert is ~1.1 KB like the simulator's alerts
        # (the alert item's size drives the WCU of every metrics event).
        "transactionId": uuid.uuid4().hex,
        "operationDate": created_at.isoformat(),
        "triggeredRules": [
            f"R{rng.randint(100, 999)}" for _ in range(rng.randint(1, 4))
        ],
        "score": round(rng.random(), 4),
        "device": {
            "id": uuid.uuid4().hex,
            "os": rng.choice(["android", "ios", "web"]),
            "ip": f"10.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(256)}",
        },
        "beneficiary": {
            "bank": rng.choice(["0001", "0007", "0013", "0051"]),
            "accountHash": uuid.uuid4().hex + uuid.uuid4().hex,
        },
        "description": "synthetic load alert " + "x" * rng.randint(150, 350),
    }
    alert = AlertRecord(
        id=alert_id,
        event_id=f"syn-{alert_id.hex[:12]}",
        event_type="payment",
        input=payload,
        status=AlertStatus.RECEIVED,
        created_at=created_at,
        updated_at=created_at,
        customer_id=None,
    )
    # Configuration switched one third of the way through the 90 days.
    configuration_id = CONFIGURATION_IDS[0 if (now - created_at).days > 60 else 1]
    events = [
        PlannedEvent(
            created_at,
            "created",
            I(alert_id, E.CREATED, created_at, origin=_pick(rng, ORIGINS)),
        ),
        PlannedEvent(
            created_at + timedelta(seconds=3),
            "pre_processed",
            I(
                alert_id,
                E.PRE_PROCESSED,
                created_at + timedelta(seconds=3),
                segment=_pick(rng, SEGMENTS),
                configuration_id=configuration_id,
            ),
        ),
    ]
    action, status = rng.choices(
        [(a, s) for a, s, _ in WORKFLOW_OUTCOMES],
        weights=[w for *_, w in WORKFLOW_OUTCOMES],
    )[0]
    workflow_id = uuid.uuid4()
    steps, finished = _steps_for(
        rng, workflow_id, created_at + timedelta(seconds=3), action
    )
    # Queue wait before the run (Celery backlog), 0-90 s.
    finished += timedelta(seconds=rng.uniform(0, 90))
    events.append(
        PlannedEvent(
            finished,
            "workflow_finished",
            I(
                alert_id,
                E.WORKFLOW_FINISHED,
                finished,
                status=AlertStatus(status),
                executed_action=action,
            ),
        )
    )
    if tech:
        events.append(PlannedEvent(finished, "steps", workflow_id))
    mark = {"none": Mark.NO_FRAUD, "discarded": Mark.NO_FRAUD, "block": Mark.FRAUD}.get(
        action or ""
    )
    decided_at = finished
    if action == "scale_to_analyst":
        decided_at = finished + timedelta(minutes=rng.lognormvariate(math.log(20), 0.9))
        decision = _pick(rng, ANALYST_DECISIONS)
        events.append(
            PlannedEvent(
                decided_at,
                "analyst_resolved",
                I(alert_id, E.ANALYST_RESOLVED, decided_at, decision=decision),
            )
        )
        mark = {"pass": Mark.NO_FRAUD, "block": Mark.FRAUD}.get(decision)
    elif action == "voicebot":
        decided_at = finished + timedelta(minutes=rng.uniform(1, 25))
        outcome = _pick(rng, VOICEBOT_OUTCOMES)
        events.append(
            PlannedEvent(
                decided_at,
                "voicebot_completed",
                I(alert_id, E.VOICEBOT_COMPLETED, decided_at, outcome=outcome),
            )
        )
        mark = {
            "customer_recognized": Mark.NO_FRAUD,
            "customer_not_recognized": Mark.FRAUD,
        }.get(outcome)
    if mark is not None and rng.random() < REVIEW_PROBABILITY:
        reviews = 2 if rng.random() < SECOND_REVIEW_PROBABILITY else 1
        at = decided_at
        label = mark
        for _ in range(reviews):
            if rng.random() < 0.98:
                at = at + timedelta(
                    seconds=rng.expovariate(1 / (1.2 * 86400)) % (4 * 86400)
                )
            else:
                at = at + timedelta(days=rng.uniform(4, 183))
            if rng.random() < REVIEW_FLIP_PROBABILITY:
                label = Mark.FRAUD if label == Mark.NO_FRAUD else Mark.NO_FRAUD
            if at > now:
                break
            events.append(
                PlannedEvent(
                    at,
                    "fraud_reviewed",
                    I(alert_id, E.FRAUD_REVIEWED, at, fraud_label=label),
                )
            )
    events.sort(key=lambda e: e.at)
    return alert, events, (workflow_id, steps) if tech else None


# --- worker ---------------------------------------------------------------------------


def _with_retry(fn, tally: Tally, attempts: int = 8):
    for attempt in range(attempts):
        try:
            return fn()
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            # InternalServerError: DynamoDB Local's "timed out waiting for a
            # lock" under concurrent transactions (real DynamoDB would not).
            if code not in (
                "TransactionCanceledException",
                "TransactionConflictException",
                "ThrottlingException",
                "ProvisionedThroughputExceededException",
                "InternalServerError",
            ):
                raise
            tally.conflicts += 1
            time.sleep(0.01 * (2**attempt) * random.random())
    return fn()


def run_worker(
    args: tuple[list[str], int, float, str, str, int, float],
) -> dict[str, Any]:
    day_isos, per_day, tech_sample, now_iso, tier_change_iso, seed, probe_rate = args
    from src.application.dtos.technical_metrics_dtos import (
        RecordWorkflowStepMetricsInput,
    )
    from src.application.use_cases.metrics.record_alert_metrics_event import (
        RecordAlertMetricsEvent,
    )
    from src.application.use_cases.metrics.record_workflow_step_metrics import (
        RecordWorkflowStepMetrics,
    )
    from src.infrastructure.persistence.database.dynamodb.client import (
        get_dynamodb_resource,
    )
    from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
        DynamoAlertRepository,
    )
    from src.infrastructure.persistence.database.dynamodb.repositories.metrics_rollup_repository import (
        DynamoMetricsRollupRepository,
    )

    tally = Tally()
    install_capacity_hooks(get_dynamodb_resource().meta.client, tally, probe_rate)
    now = datetime.fromisoformat(now_iso)
    clock = Clock()
    alerts = DynamoAlertRepository(TZ_NAME)
    rollups = DynamoMetricsRollupRepository(TZ_NAME)
    steps_repo = InMemoryStepRepository()
    writer = RecordAlertMetricsEvent(
        alert_repository=alerts,
        rollup_repository=rollups,
        settings_repository=TierSwitchingSettings(
            clock, datetime.fromisoformat(tier_change_iso)
        ),
        timezone_name=TZ_NAME,
        clock=clock,
    )
    technical = RecordWorkflowStepMetrics(
        alert_repository=alerts,
        step_repository=steps_repo,
        rollup_repository=rollups,
        timezone_name=TZ_NAME,
        clock=clock,
    )
    counts: Counter = Counter()
    for day_iso in day_isos:
        day = date.fromisoformat(day_iso)
        rng = random.Random(f"{seed}-{day_iso}")
        n = max(0, int(rng.gauss(per_day, per_day * 0.08)))
        created = sorted(_created_at(rng, day) for _ in range(n))
        for created_at in created:
            if created_at >= now:
                continue
            alert, events, tech = plan_alert(
                rng, created_at, now, rng.random() < tech_sample
            )
            if tech is not None:
                steps_repo.by_workflow = {tech[0]: tech[1]}
            try:
                _current.tag = "alert_put"
                _with_retry(lambda: alerts.create(alert), tally)
                counts["alerts"] += 1
                for event in events:
                    clock.now = event.at
                    _current.tag = event.tag
                    if event.tag == "steps":
                        _with_retry(
                            lambda: technical.execute(
                                RecordWorkflowStepMetricsInput(
                                    alert_id=alert.id,
                                    workflow_execution_id=event.input,
                                    step_models=LLM_STEP_MODELS,
                                )
                            ),
                            tally,
                        )
                        counts["step_records"] += len(tech[1])
                    else:
                        _with_retry(lambda: writer.execute(event.input), tally)
                    counts[event.tag] += 1
            except Exception as exc:  # noqa: BLE001 - keep the run and tally going
                counts["failed_alerts"] += 1
                counts[f"error:{type(exc).__name__}"] += 1
        print(f"[worker] {day_iso} done: {counts['alerts']} alerts so far", flush=True)
    return {
        "counts": dict(counts),
        "calls": dict(tally.calls),
        "items": dict(tally.items),
        "units": dict(tally.units),
        "probed": dict(tally.probed),
        "modeled_wcu": dict(tally.modeled_wcu),
        "probed_items": dict(tally.probed_items),
        "probed_items_over_1kb": dict(tally.probed_items_over_1kb),
        "conflicts": tally.conflicts,
    }


# --- storage report ---------------------------------------------------------------------


def _attr_size(value: Any) -> int:
    """Approximate DynamoDB attribute value size (bytes)."""
    if isinstance(value, str):
        return len(value.encode())
    if isinstance(value, bool) or value is None:
        return 1
    if isinstance(value, (int, float, Decimal)):
        digits = len(str(abs(value)).replace(".", "").lstrip("0")) or 1
        return 1 + math.ceil(digits / 2)
    if isinstance(value, dict):
        return 3 + sum(len(k.encode()) + _attr_size(v) + 1 for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return 3 + sum(_attr_size(v) + 1 for v in value)
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    return len(str(value))


def item_size(item: dict[str, Any]) -> int:
    return sum(len(k.encode()) + _attr_size(v) for k, v in item.items())


def storage_report(now: datetime) -> dict[str, Any]:
    from src.infrastructure.persistence.database.dynamodb.client import (
        get_dynamodb_resource,
    )

    table = get_dynamodb_resource().Table("metrics_rollups")
    kwargs: dict[str, Any] = {}
    by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    partitions: dict[tuple[str, str], set[str]] = defaultdict(set)
    attrs: dict[tuple[str, str], list[int]] = defaultdict(list)
    expired_day_rows = 0
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            pk = item["pk"]
            if pk.startswith("marker#"):
                key = ("marker", "-")
            else:
                data_type, level, period = pk.split("#", 2)
                key = (data_type, level)
                partitions[key].add(period)
                if level == "day" and int(item.get("expires_at", 0)) < now.timestamp():
                    expired_day_rows += 1
            by_key[key].append(item_size(item))
            attrs[key].append(sum(1 for a in item if "__h" in a))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    report = {}
    for key, sizes in sorted(by_key.items()):
        sizes.sort()
        n_periods = len(partitions.get(key, ())) or 1
        report[f"{key[0]}#{key[1]}"] = {
            "items": len(sizes),
            "periods": len(partitions.get(key, ())),
            "items_per_period": round(len(sizes) / n_periods, 1),
            "bytes": sum(sizes),
            "avg_item_bytes": round(sum(sizes) / len(sizes)),
            "p95_item_bytes": sizes[int(0.95 * (len(sizes) - 1))],
            "max_item_bytes": sizes[-1],
            "avg_measure_attrs": round(sum(attrs[key]) / len(attrs[key]), 1),
        }
    description = table.meta.client.describe_table(TableName="metrics_rollups")["Table"]
    alerts = table.meta.client.describe_table(TableName="alerts")["Table"]
    return {
        "rollups": report,
        "expired_day_rows_still_stored": expired_day_rows,
        "metrics_rollups_table": {
            "ItemCount": description.get("ItemCount"),
            "TableSizeBytes": description.get("TableSizeBytes"),
        },
        "alerts_table": {
            "ItemCount": alerts.get("ItemCount"),
            "TableSizeBytes": alerts.get("TableSizeBytes"),
        },
    }


# --- main -------------------------------------------------------------------------------


def _ensure_tables() -> None:
    from src.infrastructure.persistence.database.dynamodb.manager import (
        create_table,
        enable_ttl,
        ensure_global_secondary_indexes,
    )
    from src.infrastructure.persistence.database.dynamodb.schemas import (
        ALERTS_TABLE,
        METRICS_ROLLUPS_TABLE,
    )

    create_table(ALERTS_TABLE)
    ensure_global_secondary_indexes(ALERTS_TABLE)
    create_table(METRICS_ROLLUPS_TABLE)
    enable_ttl(METRICS_ROLLUPS_TABLE, "expires_at")


def _refuse_shared_endpoint(allow: bool) -> None:
    from src.infrastructure.core.config import genai_config

    endpoint = genai_config.DYNAMO_ENDPOINT or ""
    if not endpoint:
        raise SystemExit(
            "Refusing to run against real AWS DynamoDB (DYNAMO_ENDPOINT is empty)."
        )
    if endpoint.rstrip("/").endswith(":8002") and not allow:
        raise SystemExit(
            f"Refusing to write synthetic data into the local stack's DynamoDB ({endpoint}). "
            "Start a throwaway DynamoDB Local (see `make metrics-synthetic-load`) "
            "or pass --i-know-this-is-shared."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--per-day", type=int, default=1500)
    parser.add_argument(
        "--offset-days",
        type=int,
        default=0,
        help="Shift the window this many days into the past (older history).",
    )
    parser.add_argument("--tech-sample", type=float, default=0.1)
    parser.add_argument(
        "--tier-change-day",
        type=int,
        default=None,
        help="Day index (from the oldest) the amount tiers are configured. Default: middle.",
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--probe-rate",
        type=float,
        default=0.02,
        help="Share of transactions re-read to model their size-based WCU.",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument(
        "--skip-report",
        action="store_true",
        help="Skip the final table scan (when loading in chunks).",
    )
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--i-know-this-is-shared", action="store_true")
    args = parser.parse_args(argv)
    _refuse_shared_endpoint(args.i_know_this_is_shared)

    now = datetime.now(UTC)
    today = now.astimezone(TZ).date() - timedelta(days=args.offset_days)
    days = [today - timedelta(days=i) for i in range(args.days - 1, -1, -1)]
    result: dict[str, Any] = {"args": vars(args)}
    if not args.report_only:
        _ensure_tables()
        change_index = (
            args.tier_change_day if args.tier_change_day is not None else args.days // 2
        )
        change_day = days[min(change_index, len(days) - 1)]
        tier_change_at = datetime(
            change_day.year, change_day.month, change_day.day, tzinfo=TZ
        )
        chunks = [
            [d.isoformat() for d in days[i :: args.workers]]
            for i in range(args.workers)
        ]
        jobs = [
            (
                c,
                args.per_day,
                args.tech_sample,
                now.isoformat(),
                tier_change_at.isoformat(),
                args.seed,
                args.probe_rate,
            )
            for c in chunks
            if c
        ]
        started = time.perf_counter()
        with multiprocessing.get_context("spawn").Pool(len(jobs)) as pool:
            parts = pool.map(run_worker, jobs)
        elapsed = time.perf_counter() - started
        merged: dict[str, Counter] = {
            k: Counter()
            for k in (
                "counts",
                "calls",
                "items",
                "units",
                "probed",
                "modeled_wcu",
                "probed_items",
                "probed_items_over_1kb",
            )
        }
        conflicts = 0
        for part in parts:
            for k in merged:
                merged[k].update(part[k])
            conflicts += part["conflicts"]
        counts = merged["counts"]
        writer_events = sum(
            v
            for k, v in counts.items()
            if k not in ("alerts", "steps", "step_records", "failed_alerts")
            and not k.startswith("error:")
        )
        result.update(
            {
                "elapsed_seconds": round(elapsed, 1),
                "alerts_per_second": round(counts["alerts"] / elapsed, 1),
                "metrics_events_per_second": round(writer_events / elapsed, 1),
                "tier_change_day": change_day.isoformat(),
                "counts": dict(counts),
                "transaction_retries": conflicts,
                "capacity": {
                    key: {
                        "calls": merged["calls"][key],
                        "items": merged["items"].get(key, 0),
                        "units": round(merged["units"][key], 1),
                        "units_per_call": round(
                            merged["units"][key] / merged["calls"][key], 2
                        ),
                        "items_per_call": round(
                            merged["items"].get(key, 0) / merged["calls"][key], 2
                        ),
                    }
                    for key in sorted(merged["calls"])
                },
                "modeled_transaction_wcu": {
                    tag: {
                        "sampled_transactions": merged["probed"][tag],
                        "wcu_per_transaction": round(
                            merged["modeled_wcu"][tag] / merged["probed"][tag], 2
                        ),
                        "items_per_transaction": round(
                            merged["probed_items"][tag] / merged["probed"][tag], 2
                        ),
                        "share_items_over_1kb": round(
                            merged["probed_items_over_1kb"][tag]
                            / merged["probed_items"][tag],
                            3,
                        ),
                    }
                    for tag in sorted(merged["probed"])
                },
            }
        )
    if not args.skip_report:
        result["storage"] = storage_report(now)
    text = json.dumps(result, indent=2, default=str)
    print(text)
    if args.json_path:
        with open(args.json_path, "w") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
