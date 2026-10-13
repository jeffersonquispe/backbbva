import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from src.application.dtos.alert_dtos import StartAlertWorkflowInput
from src.application.ports.alert_port import AlertRecord, AlertStatus
from src.application.ports.object_storage_port import ObjectStorageRef
from src.application.ports.workflow_executor_port import WorkflowExecutionRef
from src.application.use_cases.alerts.raw_payload import RawAlertPayloadLoader
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)


class RecordingStorage:
    def __init__(self):
        self.objects = {}

    def put_text(self, key, content, content_type="text/plain"):
        self.objects[key] = content.encode()
        return ObjectStorageRef("bucket", key, f"s3://bucket/{key}")

    def get_bytes(self, key):
        return self.objects[key]


class Alerts:
    def __init__(self):
        self.items = {}

    def create(self, alert):
        self.items[alert.id] = alert
        return alert

    def get(self, alert_id):
        return self.items.get(alert_id)

    def update(self, alert_id, **changes):
        current = self.items[alert_id]
        self.items[alert_id] = AlertRecord(
            **{**current.__dict__, **changes, "updated_at": current.updated_at}
        )
        return self.items[alert_id]


class Operations:
    def create(self, item):
        return item

    def update(self, operation_id, **changes):
        return None


class Workflows:
    def create(self, item):
        return item

    def update(self, workflow_id, **changes):
        return None


class Executor:
    def start(self, workflow):
        return WorkflowExecutionRef(backend="memory", external_id="run-1")


def test_alert_creation_persists_only_a_raw_payload_reference():
    storage = RecordingStorage()
    alerts = Alerts()
    use_case = StartAlertTestWorkflowUseCase(
        alerts, Operations(), Workflows(), Executor(), object_storage=storage
    )
    payload = {"eventId": "evt-1", "eventType": "payment", "customerId": "c-1"}

    result = use_case.execute(StartAlertWorkflowInput(payload=payload))
    alert = alerts.get(result.alert_id)

    assert alert.raw_payload_ref.key in storage.objects
    assert json.loads(storage.objects[alert.raw_payload_ref.key]) == payload
    assert not hasattr(alert, "payload")


def test_raw_loader_requires_the_canonical_object_reference():
    storage = RecordingStorage()
    loader = RawAlertPayloadLoader(storage)
    alert = AlertRecord(
        UUID(int=1), "evt", "payment", AlertStatus.RECEIVED,
        datetime.now(UTC), datetime.now(UTC)
    )

    with pytest.raises(ValueError, match="raw payload reference"):
        loader.load(alert)

