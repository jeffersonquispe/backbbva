"""DynamoDB MetricsRollupRepository (R3).

Row layout (table metrics_rollups, see schemas.METRICS_ROLLUPS_TABLE):
- pk  "<data_type>#<level>#<period>"     e.g. "alert#day#2026-10-01"
- sk  dimensions in their fixed order, "name=value|name=value|..." with
      each value percent-encoded (so "|" / "=" in a value can't collide)
- dims         map of the same dimensions (readable without parsing sk)
- data_type, level, period
- "<measure>__h<HH>"  one top-level number per measure and hour of day.
  Flat on purpose: DynamoDB's ADD only works on top-level attributes - a
  nested map path (m.h03) or list index (l[3]) is rejected with "The
  document path provided in the update expression is invalid for update"
  (checked against DynamoDB Local, R3 spike).
- expires_at   TTL epoch seconds, day rows only.
- rev          row revision, ADD 1 on every write (R7 conditional correction).

apply() is ONE TransactWriteItems: the alert's snapshot update conditioned
on snapshot_version, plus one ADD update per touched row. Either all of it
lands or none, so a Celery retry or a concurrent event can never count an
alert twice."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.metrics_rollup_port import (
    DAY_LEVEL_RETENTION_DAYS,
    AlertSnapshotGuard,
    MetricsDataType,
    RollupApplyMarker,
    RollupDelta,
    RollupKey,
    RollupLevel,
    RollupRow,
)
from src.domain.alerts.exceptions import SnapshotVersionConflictError
from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    METRICS_ATTRIBUTE,
    PARTITION as ALERTS_PARTITION,
    TABLE_NAME as ALERTS_TABLE_NAME,
    created_day_for,
    snapshot_to_item,
)

TABLE_NAME = "metrics_rollups"
TTL_ATTRIBUTE = "expires_at"
# TransactWriteItems caps a transaction at 100 items; one is the alert.
MAX_ROWS_PER_APPLY = 99

# apply_once markers live in this same table under their own pk prefix
# ("marker#<scope>#<key>", sk "marker") - never matched by a query(), whose
# pk is always "<data_type>#<level>#<period>". They only have to outlive
# every possible redelivery/retry of their event; a generous TTL keeps the
# table from growing forever.
MARKER_SORT_KEY = "marker"
MARKER_RETENTION_DAYS = 400

# Row revision: ADD 1 on every write (apply, apply_once, correct), so the
# R7 reconciliation can make its correction conditional on "nobody wrote
# this row since I read it" and never race a live delta.
REVISION_ATTRIBUTE = "rev"
# DynamoDB caps an expression at 4 KB: a correction touching more measure
# attributes than this is split into chained conditional updates.
MAX_ATTRIBUTES_PER_CORRECTION = 100
# Two stored numbers closer than this are equal (float sums vs Decimal).
_TOLERANCE = 1e-6

_MEASURE_ATTRIBUTE = re.compile(r"^(?P<measure>.+)__h(?P<hour>\d{2})$")


def partition_key(data_type: MetricsDataType, level: RollupLevel, period: str) -> str:
    return f"{data_type.value}#{level.value}#{period}"


def marker_partition_key(marker: RollupApplyMarker) -> str:
    return f"marker#{marker.scope}#{marker.key}"


def sort_key(dimensions: tuple[tuple[str, str], ...]) -> str:
    return "|".join(f"{name}={quote(value, safe='')}" for name, value in dimensions)


def measure_attribute(measure: str, hour: int) -> str:
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be 0-23, got {hour}")
    return f"{measure}__h{hour:02d}"


def day_row_expiry(period: str) -> int:
    """Epoch seconds when a day row may be deleted: one day after the last
    date it can still be written (age 89)."""
    day = date.fromisoformat(period)
    expiry = datetime.combine(
        day + timedelta(days=DAY_LEVEL_RETENTION_DAYS + 1), time(), tzinfo=timezone.utc
    )
    return int(expiry.timestamp())


def _number(value: float) -> Decimal:
    if isinstance(value, int) or float(value).is_integer():
        return Decimal(int(value))
    return Decimal(str(value))


class DynamoMetricsRollupRepository:
    def __init__(self, timezone_name: str | None = None) -> None:
        resource = get_dynamodb_resource()
        # transact_write_items takes plain Python values, like Table calls.
        self._client = resource.meta.client
        self._table = resource.Table(TABLE_NAME)
        self._timezone_name = timezone_name or genai_config.OPERATIONS_TIMEZONE

    def apply(self, deltas: list[RollupDelta], alert_guard: AlertSnapshotGuard) -> None:
        rows = _merge_rows(deltas)
        items = [self._alert_update(alert_guard)]
        items.extend(self._row_update(key, increments) for key, increments in rows.items())
        try:
            self._client.transact_write_items(TransactItems=items)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            reasons = exc.response.get("CancellationReasons") or []
            if reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
                raise SnapshotVersionConflictError(
                    str(alert_guard.alert_id), alert_guard.expected_version
                ) from exc
            raise

    def apply_once(self, deltas: list[RollupDelta], marker: RollupApplyMarker) -> bool:
        """Same transaction shape as apply(), with the idempotency marker in
        the alert's place: a Put of the marker item conditioned on
        attribute_not_exists. A redelivered/retried event finds its marker
        and the whole transaction (marker + every ADD) is cancelled."""
        rows = _merge_rows(deltas)
        items = [self._marker_put(marker)]
        items.extend(self._row_update(key, increments) for key, increments in rows.items())
        try:
            self._client.transact_write_items(TransactItems=items)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            reasons = exc.response.get("CancellationReasons") or []
            if reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
                return False
            raise
        return True

    def query(
        self,
        data_type: MetricsDataType,
        level: RollupLevel,
        periods: list[str],
        filters: dict[str, list[str]] | None = None,
    ) -> list[RollupRow]:
        accepted = {
            name: {str(value) for value in values}
            for name, values in (filters or {}).items()
        }
        rows: list[RollupRow] = []
        for period in periods:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("pk").eq(
                    partition_key(data_type, level, period)
                )
            }
            while True:
                response = self._table.query(**kwargs)
                for item in response.get("Items", []):
                    row = _row_from_item(item, data_type, level, period)
                    if all(
                        row.key.dimension(name) in values
                        for name, values in accepted.items()
                    ):
                        rows.append(row)
                if "LastEvaluatedKey" not in response:
                    break
                kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return rows

    def correct(
        self,
        key: RollupKey,
        measures: dict[str, list[float]],
        expected_revision: int | None,
    ) -> bool:
        """R7 only. Sets just the attributes that differ, conditioned on the
        revision the caller read (None = row absent); each chunk bumps the
        revision, the next chunk is conditioned on that. A live write in
        between fails the condition: we stop (the attributes already set
        were correct at that point and the live ADD lands on top of them)
        and the rest is retried by the next run."""
        item_key = {
            "pk": partition_key(key.data_type, key.level, key.period),
            "sk": sort_key(key.dimensions),
        }
        item = self._table.get_item(Key=item_key, ConsistentRead=True).get("Item")
        current = None if item is None else int(item.get(REVISION_ATTRIBUTE, 0))
        if current != expected_revision:
            return False
        stored = {
            attribute: float(value)
            for attribute, value in (item or {}).items()
            if _MEASURE_ATTRIBUTE.match(attribute)
        }
        target = {
            measure_attribute(measure, hour): float(value)
            for measure, slots in measures.items()
            for hour, value in enumerate(slots)
            if value
        }
        changes = sorted(
            (attribute, target.get(attribute, 0.0))
            for attribute in set(stored) | set(target)
            if not _same(stored.get(attribute, 0.0), target.get(attribute, 0.0))
        )
        revision = expected_revision
        for start in range(0, len(changes), MAX_ATTRIBUTES_PER_CORRECTION):
            chunk = changes[start : start + MAX_ATTRIBUTES_PER_CORRECTION]
            names, values, sets = _row_static_sets(key)
            names["#rev"] = REVISION_ATTRIBUTE
            values[":rev_one"] = 1
            removes: list[str] = []
            for index, (attribute, value) in enumerate(chunk):
                names[f"#a{index}"] = attribute
                if value == 0:
                    removes.append(f"#a{index}")
                else:
                    values[f":a{index}"] = _number(value)
                    sets.append(f"#a{index} = :a{index}")
            if revision is None:
                condition = "attribute_not_exists(pk)"
            elif revision == 0:
                condition = "attribute_exists(pk) AND attribute_not_exists(#rev)"
            else:
                condition = "#rev = :expected_rev"
                values[":expected_rev"] = revision
            expression = "SET " + ", ".join(sets)
            if removes:
                expression += " REMOVE " + ", ".join(removes)
            expression += " ADD #rev :rev_one"
            try:
                self._table.update_item(
                    Key=item_key,
                    UpdateExpression=expression,
                    ConditionExpression=condition,
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    return False
                raise
            revision = (revision or 0) + 1
        return True

    # --- transaction items ------------------------------------------------------

    def _alert_update(self, guard: AlertSnapshotGuard) -> dict[str, Any]:
        names = {
            "#metrics": METRICS_ATTRIBUTE,
            "#created_day": "created_day",
        }
        values: dict[str, Any] = {
            ":snapshot": snapshot_to_item(guard.snapshot),
            ":created_day": created_day_for(guard.alert_created_at, self._timezone_name),
        }
        if guard.expected_version == 0:
            condition = "attribute_exists(alert_id) AND attribute_not_exists(#metrics)"
        else:
            condition = "#metrics.#version = :expected"
            names["#version"] = "snapshot_version"
            values[":expected"] = guard.expected_version
        return {
            "Update": {
                "TableName": ALERTS_TABLE_NAME,
                "Key": {"partition": ALERTS_PARTITION, "alert_id": str(guard.alert_id)},
                "UpdateExpression": (
                    "SET #metrics = :snapshot, "
                    "#created_day = if_not_exists(#created_day, :created_day)"
                ),
                "ConditionExpression": condition,
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        }

    def _marker_put(self, marker: RollupApplyMarker) -> dict[str, Any]:
        expires_at = datetime.now(timezone.utc) + timedelta(days=MARKER_RETENTION_DAYS)
        return {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": {
                    "pk": marker_partition_key(marker),
                    "sk": MARKER_SORT_KEY,
                    "scope": marker.scope,
                    TTL_ATTRIBUTE: int(expires_at.timestamp()),
                },
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        }

    def _row_update(self, key: RollupKey, increments: dict[str, float]) -> dict[str, Any]:
        names: dict[str, str] = {
            "#data_type": "data_type",
            "#level": "level",
            "#period": "period",
            "#dims": "dims",
        }
        values: dict[str, Any] = {
            ":data_type": key.data_type.value,
            ":level": key.level.value,
            ":period": key.period,
            ":dims": {name: value for name, value in key.dimensions},
        }
        sets = [
            "#data_type = if_not_exists(#data_type, :data_type)",
            "#level = if_not_exists(#level, :level)",
            "#period = if_not_exists(#period, :period)",
            "#dims = if_not_exists(#dims, :dims)",
        ]
        if key.level == RollupLevel.DAY:
            names["#ttl"] = TTL_ATTRIBUTE
            values[":ttl"] = day_row_expiry(key.period)
            sets.append("#ttl = :ttl")
        # Every write bumps the row revision (see correct()).
        names["#rev"] = REVISION_ATTRIBUTE
        values[":rev_one"] = 1
        adds = ["#rev :rev_one"]
        for index, (attribute, value) in enumerate(sorted(increments.items())):
            names[f"#m{index}"] = attribute
            values[f":m{index}"] = _number(value)
            adds.append(f"#m{index} :m{index}")
        return {
            "Update": {
                "TableName": TABLE_NAME,
                "Key": {
                    "pk": partition_key(key.data_type, key.level, key.period),
                    "sk": sort_key(key.dimensions),
                },
                "UpdateExpression": "SET " + ", ".join(sets) + " ADD " + ", ".join(adds),
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        }


def _same(left: float, right: float) -> bool:
    return abs(left - right) <= _TOLERANCE * max(1.0, abs(right))


def _row_static_sets(key: RollupKey) -> tuple[dict[str, str], dict[str, Any], list[str]]:
    """The descriptive attributes a row carries besides its measures, as
    if_not_exists SETs (same as _row_update) - for correct()."""
    names: dict[str, str] = {
        "#data_type": "data_type",
        "#level": "level",
        "#period": "period",
        "#dims": "dims",
    }
    values: dict[str, Any] = {
        ":data_type": key.data_type.value,
        ":level": key.level.value,
        ":period": key.period,
        ":dims": {name: value for name, value in key.dimensions},
    }
    sets = [
        "#data_type = if_not_exists(#data_type, :data_type)",
        "#level = if_not_exists(#level, :level)",
        "#period = if_not_exists(#period, :period)",
        "#dims = if_not_exists(#dims, :dims)",
    ]
    if key.level == RollupLevel.DAY:
        names["#ttl"] = TTL_ATTRIBUTE
        values[":ttl"] = day_row_expiry(key.period)
        sets.append("#ttl = :ttl")
    return names, values, sets


def _merge_rows(deltas: list[RollupDelta]) -> dict[RollupKey, dict[str, float]]:
    """Deltas -> per row, its non-zero "<measure>__h<HH>" increments."""
    rows: dict[RollupKey, dict[str, float]] = defaultdict(dict)
    for delta in deltas:
        increments = rows[delta.key]
        for measure, value in delta.measures.items():
            attribute = measure_attribute(measure, delta.hour)
            increments[attribute] = increments.get(attribute, 0) + value
    merged = {
        key: {attr: value for attr, value in increments.items() if value != 0}
        for key, increments in rows.items()
    }
    merged = {key: increments for key, increments in merged.items() if increments}
    if len(merged) > MAX_ROWS_PER_APPLY:
        raise ValueError(
            f"{len(merged)} rollup rows in one apply, max {MAX_ROWS_PER_APPLY}"
        )
    return merged


def _row_from_item(
    item: dict[str, Any], data_type: MetricsDataType, level: RollupLevel, period: str
) -> RollupRow:
    dims = item.get("dims") or {}
    measures: dict[str, list[float]] = {}
    for attribute, value in item.items():
        match = _MEASURE_ATTRIBUTE.match(attribute)
        if match is None:
            continue
        slots = measures.setdefault(match.group("measure"), [0.0] * 24)
        number = float(value)
        slots[int(match.group("hour"))] = int(number) if number.is_integer() else number
    # Dimension order as written (dims map order isn't guaranteed; the sk
    # carries the canonical order).
    order = [part.split("=", 1)[0] for part in str(item.get("sk", "")).split("|") if part]
    dimensions = tuple((name, str(dims.get(name, ""))) for name in order if name in dims)
    return RollupRow(
        key=RollupKey(
            data_type=data_type, level=level, period=period, dimensions=dimensions
        ),
        measures=measures,
        revision=int(item.get(REVISION_ATTRIBUTE, 0)),
    )
