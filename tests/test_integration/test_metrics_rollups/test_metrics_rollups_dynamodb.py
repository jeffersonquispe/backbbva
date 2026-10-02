"""Q2 - Docker-only integration tests against DynamoDB Local: the
TransactWriteItems (snapshot condition + ADD deltas), retry without double
counting, version race, TTL on day rows and the created_day index - what
an in-memory fake can't prove. Run with `make test-integration-metrics`."""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip("Requires DynamoDB Local (set DYNAMO_ENDPOINT)", allow_module_level=True)

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.ports.alert_port import AlertRecord, AlertStatus, Mark
from src.application.ports.metrics_rollup_port import (
    AlertSnapshotGuard,
    MetricsDataType,
    RollupLevel,
)
from src.application.ports.operational_settings_port import (
    AmountTier,
    OperationalSettings,
)
from src.application.use_cases.metrics.alert_rollup_contribution import diff
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.domain.alerts.exceptions import SnapshotVersionConflictError
from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource
from src.infrastructure.persistence.database.dynamodb.manager import (
    create_table,
    ensure_global_secondary_indexes,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    PARTITION,
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.metrics_rollup_repository import (
    DynamoMetricsRollupRepository,
    partition_key,
    sort_key,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERTS_TABLE,
    METRICS_ROLLUPS_TABLE,
)

pytestmark = pytest.mark.docker_integration

TZ = "America/Bogota"
PAYLOAD = {"channel": "WEB", "integrationPoint": "PSE", "amount": {"baseValue": 1500}}


class StaticSettings:
    def get(self) -> OperationalSettings:
        return OperationalSettings(
            amount_tiers=[AmountTier("low", "low", 0, 1000), AmountTier("high", "high", 1000, None)],
            amount_tier_set_version=1,
        )


@pytest.fixture(scope="module")
def repos():
    create_table(ALERTS_TABLE)
    ensure_global_secondary_indexes(ALERTS_TABLE)
    create_table(METRICS_ROLLUPS_TABLE)
    return DynamoAlertRepository(TZ), DynamoMetricsRollupRepository(TZ)


@pytest.fixture
def cleanup():
    """Collects alert ids; deletes them and every rollup row they touched."""
    alert_ids: list[uuid.UUID] = []
    yield alert_ids
    resource = get_dynamodb_resource()
    alerts_table = resource.Table(ALERTS_TABLE["TableName"])
    rollups_table = resource.Table(METRICS_ROLLUPS_TABLE["TableName"])
    alerts = DynamoAlertRepository(TZ)
    for alert_id in alert_ids:
        alert = alerts.get(alert_id)
        if alert is not None and alert.metrics is not None:
            for delta in diff(None, alert.metrics, alert.created_at, datetime.now(timezone.utc), TZ):
                rollups_table.delete_item(
                    Key={
                        "pk": partition_key(delta.key.data_type, delta.key.level, delta.key.period),
                        "sk": sort_key(delta.key.dimensions),
                    }
                )
        alerts_table.delete_item(Key={"partition": PARTITION, "alert_id": str(alert_id)})


def _alert(alerts: DynamoAlertRepository, created_at: datetime, cleanup) -> AlertRecord:
    alert = alerts.create(
        AlertRecord(
            id=uuid.uuid4(),
            event_id=f"itest-{uuid.uuid4()}",
            event_type="payment",
            payload=PAYLOAD,
            status=AlertStatus.PROCESSING,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    cleanup.append(alert.id)
    return alert


def _recorder(alerts, rollups) -> RecordAlertMetricsEvent:
    return RecordAlertMetricsEvent(
        alert_repository=alerts,
        rollup_repository=rollups,
        settings_repository=StaticSettings(),
        timezone_name=TZ,
    )


def _count(rollups, level: RollupLevel, period: str, origin: str, **filters) -> float:
    rows = rollups.query(
        MetricsDataType.ALERT,
        level,
        [period],
        {"origin": [origin], **{k: [v] for k, v in filters.items()}},
    )
    return sum(row.total("count") for row in rows)


def _periods(created_at: datetime) -> dict[RollupLevel, str]:
    from zoneinfo import ZoneInfo

    local = created_at.astimezone(ZoneInfo(TZ)).date()
    return {
        RollupLevel.DAY: local.isoformat(),
        RollupLevel.MONTH: local.strftime("%Y-%m"),
        RollupLevel.YEAR: local.strftime("%Y"),
    }


def test_transaction_writes_snapshot_and_all_levels_with_ttl_on_day_only(repos, cleanup):
    alerts, rollups = repos
    origin = f"itest-{uuid.uuid4()}"
    created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    alert = _alert(alerts, created_at, cleanup)

    recorder = _recorder(alerts, rollups)
    recorder.execute(
        RecordAlertMetricsEventInput(alert.id, AlertMetricsEventType.CREATED, origin=origin)
    )
    snapshot = recorder.execute(
        RecordAlertMetricsEventInput(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.CLOSED,
            executed_action="block",
        )
    )

    stored = alerts.get(alert.id)
    assert stored.metrics == snapshot and snapshot.snapshot_version == 2
    assert stored.status == AlertStatus.PROCESSING  # snapshot write didn't touch it
    periods = _periods(created_at)
    for level, period in periods.items():
        assert _count(rollups, level, period, origin) == 1
        assert _count(rollups, level, period, origin, mark="fraud", amount_tier="high") == 1

    # TTL attribute only on the day row.
    table = get_dynamodb_resource().Table(METRICS_ROLLUPS_TABLE["TableName"])
    for level, period in periods.items():
        rows = rollups.query(MetricsDataType.ALERT, level, [period], {"origin": [origin]})
        for row in rows:
            item = table.get_item(
                Key={"pk": partition_key(MetricsDataType.ALERT, level, period), "sk": sort_key(row.key.dimensions)}
            )["Item"]
            assert ("expires_at" in item) == (level == RollupLevel.DAY)

    # A later status update by the repository keeps the snapshot.
    alerts.update(alert.id, status=AlertStatus.CLOSED)
    assert alerts.get(alert.id).metrics == snapshot


def test_retry_never_double_counts(repos, cleanup):
    alerts, rollups = repos
    origin = f"itest-{uuid.uuid4()}"
    created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    alert = _alert(alerts, created_at, cleanup)
    recorder = _recorder(alerts, rollups)
    created = RecordAlertMetricsEventInput(alert.id, AlertMetricsEventType.CREATED, origin=origin)
    first = recorder.execute(created)

    # Celery retry of the same event: no-op.
    assert recorder.execute(created) == first
    # A raw replay of the already-committed transaction: the version guard
    # rejects it and nothing is added.
    deltas = diff(None, first, alert.created_at, datetime.now(timezone.utc), TZ)
    with pytest.raises(SnapshotVersionConflictError):
        rollups.apply(
            deltas,
            AlertSnapshotGuard(alert.id, alert.created_at, expected_version=0, snapshot=first),
        )
    for level, period in _periods(created_at).items():
        assert _count(rollups, level, period, origin) == 1


def test_version_race_one_writer_fails_and_retries_on_the_new_snapshot(repos, cleanup):
    alerts, rollups = repos
    origin = f"itest-{uuid.uuid4()}"
    created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    alert = _alert(alerts, created_at, cleanup)
    _recorder(alerts, rollups).execute(
        RecordAlertMetricsEventInput(alert.id, AlertMetricsEventType.CREATED, origin=origin)
    )

    class RacingRollups:
        """Lets a competing event commit between our read and our write."""

        def __init__(self) -> None:
            self.raced = False
            self.conflicts = 0

        def apply(self, deltas, alert_guard):
            if not self.raced:
                self.raced = True
                _recorder(alerts, rollups).execute(
                    RecordAlertMetricsEventInput(
                        alert.id, AlertMetricsEventType.PRE_PROCESSED, segment="itest-seg"
                    )
                )
            try:
                rollups.apply(deltas, alert_guard)
            except SnapshotVersionConflictError:
                self.conflicts += 1
                raise

        def query(self, *args, **kwargs):
            return rollups.query(*args, **kwargs)

    racing = RacingRollups()
    result = _recorder(alerts, racing).execute(
        RecordAlertMetricsEventInput(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.CLOSED,
            executed_action="none",
        )
    )

    assert racing.conflicts == 1
    assert (result.segment, result.mark, result.snapshot_version) == ("itest-seg", Mark.NO_FRAUD, 3)
    for level, period in _periods(created_at).items():
        assert _count(rollups, level, period, origin) == 1
        assert _count(rollups, level, period, origin, segment="itest-seg", mark="no_fraud") == 1
        assert _count(rollups, level, period, origin, segment="unknown") == 0


def test_created_day_index_returns_only_that_bogota_day(repos, cleanup):
    alerts, _ = repos
    # 2001-03-04 23:30 Bogota (= 03-05 04:30 UTC) and 2001-03-05 00:30 Bogota.
    late = _alert(alerts, datetime(2001, 3, 5, 4, 30, tzinfo=timezone.utc), cleanup)
    next_day = _alert(alerts, datetime(2001, 3, 5, 5, 30, tzinfo=timezone.utc), cleanup)

    day = alerts.list_by_created_day(date(2001, 3, 4))
    ids = {a.id for a in day}
    assert late.id in ids and next_day.id not in ids
    assert next_day.id in {a.id for a in alerts.list_by_created_day(date(2001, 3, 5))}
