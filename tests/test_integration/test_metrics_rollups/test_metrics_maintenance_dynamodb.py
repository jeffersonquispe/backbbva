"""R6 backfill, R7 reconciliation and R9 status index against DynamoDB
Local - what the in-memory fakes can't prove: idempotent backfill through
the real transaction, the created_day fill for legacy alerts, the
revision-conditioned correction, and the StatusIdx count/list. Run with
`make test-integration-metrics`.

Each test works in a random past year (fake clock), so its day/month/year
rows can't collide with real local data or other runs."""
from __future__ import annotations

import os
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip("Requires DynamoDB Local (set DYNAMO_ENDPOINT)", allow_module_level=True)

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.metrics_maintenance_dtos import (
    BackfillAlertMetricsInput,
    ReconcileAlertRollupsInput,
)
from src.application.ports.alert_port import AlertRecord, AlertStatus
from src.application.ports.metrics_rollup_port import (
    MetricsDataType,
    RollupLevel,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.operational_settings_port import OperationalSettings
from src.application.ports.resource_reservation_port import (
    ReservationStatus,
    ReservedResource,
    ResourceReservation,
)
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.application.use_cases.metrics.backfill_alert_metrics import (
    BackfillAlertMetrics,
)
from src.application.use_cases.metrics.reconcile_alert_rollups import (
    ReconcileAlertRollups,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource
from src.infrastructure.persistence.database.dynamodb.manager import (
    create_table,
    ensure_global_secondary_indexes,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_lifecycle_reader import (
    DynamoAlertLifecycleReader,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    PARTITION,
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.metrics_rollup_repository import (
    DynamoMetricsRollupRepository,
    REVISION_ATTRIBUTE,
    measure_attribute,
    partition_key,
    sort_key,
)
from src.infrastructure.persistence.database.dynamodb.repositories.resource_reservation_repository import (
    RESERVATIONS_TABLE_NAME,
    _to_item as reservation_to_item,
)
from src.infrastructure.persistence.database.dynamodb.repositories.workflow_repository import (
    DynamoWorkflowExecutionRepository,
    DynamoWorkflowStepExecutionRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERTS_TABLE,
    METRICS_ROLLUPS_TABLE,
    RESOURCE_RESERVATIONS_TABLE,
    WORKFLOW_EXECUTIONS_TABLE,
    WORKFLOW_STEP_EXECUTIONS_TABLE,
)

pytestmark = pytest.mark.docker_integration

TZ = "America/Bogota"
BOG = ZoneInfo(TZ)
PAYLOAD = {"channel": "WEB", "integrationPoint": "PSE", "amount": {"baseValue": 1500}}


class StaticSettings:
    def get(self) -> OperationalSettings:
        return OperationalSettings()


class RecordingMonitoring(MonitoringPort):
    def __init__(self) -> None:
        self.drift: list[tuple[str, str, float]] = []

    def start(self, operation_name, operation_type, metadata=None):
        raise NotImplementedError

    def record_rollup_drift(self, data_type, level, drift) -> None:
        self.drift.append((data_type, level, drift))


@pytest.fixture(scope="module")
def tables():
    for schema in (
        ALERTS_TABLE,
        METRICS_ROLLUPS_TABLE,
        WORKFLOW_EXECUTIONS_TABLE,
        WORKFLOW_STEP_EXECUTIONS_TABLE,
        RESOURCE_RESERVATIONS_TABLE,
    ):
        create_table(schema)
    ensure_global_secondary_indexes(ALERTS_TABLE)


@pytest.fixture
def world(tables):
    """A random past year: DAY is two days before the fake NOW."""
    year = random.randint(1950, 1999)
    day = date(year, 3, 10)
    now = datetime(year, 3, 12, 7, 0, tzinfo=timezone.utc)
    created: dict[str, list] = {"alerts": [], "workflows": [], "reservations": []}
    yield day, now, created
    resource = get_dynamodb_resource()
    alerts_table = resource.Table(ALERTS_TABLE["TableName"])
    for alert_id in created["alerts"]:
        alerts_table.delete_item(Key={"partition": PARTITION, "alert_id": str(alert_id)})
    workflows = DynamoWorkflowExecutionRepository()
    steps = DynamoWorkflowStepExecutionRepository()
    for workflow_id in created["workflows"]:
        for step in steps.list_by_workflow(workflow_id):
            steps.delete(workflow_id, step.id)
        workflows.delete(workflow_id)
    reservations = resource.Table(RESERVATIONS_TABLE_NAME)
    for reservation_id in created["reservations"]:
        reservations.delete_item(Key={"id": reservation_id})
    rollups = resource.Table(METRICS_ROLLUPS_TABLE["TableName"])
    for level, period in (
        *((RollupLevel.DAY, (day + timedelta(days=d)).isoformat()) for d in range(-5, 3)),
        (RollupLevel.MONTH, f"{year:04d}-03"),
        (RollupLevel.YEAR, f"{year:04d}"),
    ):
        pk = partition_key(MetricsDataType.ALERT, level, period)
        items = rollups.query(
            KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": pk}
        ).get("Items", [])
        for item in items:
            rollups.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})


def _at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=BOG).astimezone(timezone.utc)


def _new_alert(created_at: datetime, status: AlertStatus, workflow_id=None) -> AlertRecord:
    return AlertRecord(
        id=uuid.uuid4(),
        event_id=f"itest-{uuid.uuid4()}",
        event_type="payment",
        input=PAYLOAD,
        status=status,
        created_at=created_at,
        updated_at=created_at,
        workflow_execution_id=workflow_id,
    )


def _workflow(created_at: datetime, alert_id, action: str, created) -> uuid.UUID:
    workflows = DynamoWorkflowExecutionRepository()
    steps = DynamoWorkflowStepExecutionRepository()
    finished = created_at + timedelta(minutes=3)
    workflow = workflows.create(
        WorkflowExecutionRecord(
            id=uuid.uuid4(),
            alert_id=alert_id,
            async_operation_id=uuid.uuid4(),
            workflow_name="alert_review",
            status=WorkflowStatus.SUCCEEDED,
            input={"origin": "production", "configuration_ref": None},
            output={"status": "completed"},
            error=None,
            current_step="post_process",
            feedback_iterations=0,
            max_feedback_iterations=3,
            created_at=created_at,
            updated_at=finished,
            finished_at=finished,
        )
    )
    created["workflows"].append(workflow.id)
    steps.create(
        WorkflowStepExecutionRecord(
            id=uuid.uuid4(),
            workflow_execution_id=workflow.id,
            step_name="executor",
            status=WorkflowStepStatus.SUCCEEDED,
            attempt=1,
            input=None,
            output={"executed_action": action},
            error=None,
            started_at=finished,
            finished_at=finished,
            created_at=finished,
            updated_at=finished,
        )
    )
    return workflow.id


def _rows(rollups, day: date) -> dict:
    out = {}
    for level, period in (
        (RollupLevel.DAY, day.isoformat()),
        (RollupLevel.MONTH, day.strftime("%Y-%m")),
        (RollupLevel.YEAR, day.strftime("%Y")),
    ):
        for row in rollups.query(MetricsDataType.ALERT, level, [period]):
            out[(level, period, row.key.dimensions)] = row.measures
    return out


def _count(rows: dict, level: RollupLevel, **dims) -> float:
    return sum(
        sum(measures.get("count", []))
        for (row_level, _, key_dims), measures in rows.items()
        if row_level == level and all(dict(key_dims).get(n) == v for n, v in dims.items())
    )


# --- R6 ------------------------------------------------------------------------------


def test_backfill_twice_yields_identical_numbers(world):
    day, now, created = world
    alerts = DynamoAlertRepository(TZ)
    rollups = DynamoMetricsRollupRepository(TZ)
    resource = get_dynamodb_resource()

    blocked = _new_alert(_at(day, 9), AlertStatus.CLOSED)
    blocked.workflow_execution_id = _workflow(blocked.created_at, blocked.id, "block", created)
    alerts.create(blocked)
    escalated = _new_alert(_at(day, 22), AlertStatus.CLOSED)
    escalated.workflow_execution_id = _workflow(
        escalated.created_at, escalated.id, "scale_to_analyst", created
    )
    alerts.create(escalated)
    reservation = ResourceReservation(
        id=f"itest-{uuid.uuid4()}",
        resource=ReservedResource.ANALYST,
        alert_id=str(escalated.id),
        holder="analyst-1",
        slot=0,
        reserved_at=escalated.created_at + timedelta(minutes=10),
        expires_at=escalated.created_at + timedelta(hours=2),
        status=ReservationStatus.RELEASED,
        released_at=escalated.created_at + timedelta(minutes=40),
        release_reason="resolved",
        detail={"decision": "pass"},
    )
    resource.Table(RESERVATIONS_TABLE_NAME).put_item(Item=reservation_to_item(reservation))
    created["reservations"].append(reservation.id)
    # A legacy alert: written before created_day existed, so absent from
    # CreatedDayIdx until the fill.
    legacy = _new_alert(_at(day, 12), AlertStatus.PROCESSING)
    alerts.create(legacy)
    resource.Table(ALERTS_TABLE["TableName"]).update_item(
        Key={"partition": PARTITION, "alert_id": str(legacy.id)},
        UpdateExpression="REMOVE created_day",
    )
    created["alerts"].extend([blocked.id, escalated.id, legacy.id])
    assert legacy.id not in {a.id for a in alerts.list_by_created_day(day)}

    assert alerts.fill_missing_created_day(day, day) >= 1
    assert alerts.fill_missing_created_day(day, day) == 0  # idempotent

    def backfill():
        recorder = RecordAlertMetricsEvent(
            alert_repository=alerts,
            rollup_repository=rollups,
            settings_repository=StaticSettings(),
            timezone_name=TZ,
            clock=lambda: now,
        )
        reader = DynamoAlertLifecycleReader(
            DynamoWorkflowExecutionRepository(), DynamoWorkflowStepExecutionRepository()
        )
        return BackfillAlertMetrics(alerts, reader, recorder).execute(
            BackfillAlertMetricsInput(day, day)
        )

    first = backfill()
    rows_after_first = _rows(rollups, day)
    second = backfill()

    assert (first.alerts_seen, first.backfilled) == (3, 3)
    assert (second.alerts_seen, second.backfilled, second.already_recorded) == (3, 0, 3)
    assert _rows(rollups, day) == rows_after_first
    for level in RollupLevel:
        assert _count(rows_after_first, level) == 3
        assert _count(rows_after_first, level, mark="fraud", resolution_method="aria") == 1
        assert _count(rows_after_first, level, mark="no_fraud", resolution_method="analyst") == 1
        assert _count(rows_after_first, level, mark="pending", status="PROCESSING", origin="unknown") == 1
    assert alerts.get(escalated.id).metrics.marked_at == reservation.released_at


# --- R7 ------------------------------------------------------------------------------


def test_reconciliation_corrects_a_hand_altered_row_and_reports_drift_1(world):
    day, now, created = world
    alerts = DynamoAlertRepository(TZ)
    rollups = DynamoMetricsRollupRepository(TZ)
    recorder = RecordAlertMetricsEvent(
        alert_repository=alerts,
        rollup_repository=rollups,
        settings_repository=StaticSettings(),
        timezone_name=TZ,
        clock=lambda: now,
    )
    for hour, action in ((10, "block"), (11, "none")):
        alert = alerts.create(_new_alert(_at(day, hour), AlertStatus.PROCESSING))
        created["alerts"].append(alert.id)
        recorder.execute(
            RecordAlertMetricsEventInput(alert.id, AlertMetricsEventType.CREATED, origin="itest")
        )
        recorder.execute(
            RecordAlertMetricsEventInput(
                alert.id,
                AlertMetricsEventType.WORKFLOW_FINISHED,
                status=AlertStatus.CLOSED,
                executed_action=action,
            )
        )
    [row] = rollups.query(
        MetricsDataType.ALERT, RollupLevel.DAY, [day.isoformat()], {"mark": ["fraud"]}
    )
    assert row.revision >= 1  # live writes bump it
    table = get_dynamodb_resource().Table(METRICS_ROLLUPS_TABLE["TableName"])
    item_key = {
        "pk": partition_key(MetricsDataType.ALERT, RollupLevel.DAY, day.isoformat()),
        "sk": sort_key(row.key.dimensions),
    }
    # Hand edit: no revision bump, like an operator or a lost write would.
    table.update_item(
        Key=item_key,
        UpdateExpression="SET #a = :v",
        ExpressionAttributeNames={"#a": measure_attribute("count", 10)},
        ExpressionAttributeValues={":v": 7},
    )

    # A stale revision can't correct: the live writer would be overwritten.
    assert rollups.correct(row.key, row.measures, row.revision - 1) is False

    def reconcile(monitoring):
        return ReconcileAlertRollups(
            alert_repository=alerts,
            rollup_repository=rollups,
            monitoring=monitoring,
            timezone_name=TZ,
            clock=lambda: now,
            settle_seconds=0,
        ).execute(ReconcileAlertRollupsInput(day_window=5, month_window=1))

    monitoring = RecordingMonitoring()
    output = reconcile(monitoring)

    assert output.drift_by_level == {"day": 1, "month": 0}
    assert output.corrected == 1 and output.skipped_concurrent == 0
    assert ("alert", "day", 1) in monitoring.drift
    stored = table.get_item(Key=item_key, ConsistentRead=True)["Item"]
    assert stored[measure_attribute("count", 10)] == 1
    assert int(stored[REVISION_ATTRIBUTE]) == row.revision + 1
    assert reconcile(RecordingMonitoring()).drift == 0


# --- R9 ------------------------------------------------------------------------------


def test_status_index_counts_and_lists_live_statuses(world):
    day, _, created = world
    alerts = DynamoAlertRepository(TZ)
    before = alerts.count_by_status(AlertStatus.RECEIVED)
    new = [alerts.create(_new_alert(_at(day, 8 + i), AlertStatus.RECEIVED)) for i in range(3)]
    created["alerts"].extend(a.id for a in new)

    assert alerts.count_by_status(AlertStatus.RECEIVED) == before + 3
    listed = [a.id for a in alerts.list_by_status(AlertStatus.RECEIVED)]
    assert [a.id for a in new] == [i for i in listed if i in {a.id for a in new}]  # oldest first

    alerts.update(new[0].id, status=AlertStatus.CLOSED)
    assert alerts.count_by_status(AlertStatus.RECEIVED) == before + 2
    assert new[0].id not in {a.id for a in alerts.list_by_status(AlertStatus.RECEIVED)}
