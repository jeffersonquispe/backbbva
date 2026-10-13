from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.application.dtos.alert_dtos import CurateAlertToDatasetInput
from src.application.ports.alert_port import AlertRecord, AlertRepository, AlertStatus
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.feedback_port import FeedbackRecord, FeedbackRepository
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowExecutionRepository,
    WorkflowStatus,
)
from src.application.use_cases.alerts.curate_alert_to_dataset import (
    CurateAlertToDatasetUseCase,
)


class InMemoryAlertRepository(AlertRepository):
    def __init__(self, alerts: dict[UUID, AlertRecord] | None = None) -> None:
        self._alerts = alerts or {}

    def create(self, alert: AlertRecord) -> AlertRecord:
        self._alerts[alert.id] = alert
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self._alerts.get(alert_id)

    def update(self, alert_id, *, status=None, async_operation_id=None, workflow_execution_id=None):
        return self._alerts.get(alert_id)

    def delete(self, alert_id: UUID) -> None:
        self._alerts.pop(alert_id, None)


class FakeDatasetRepository(DatasetRepository):
    def __init__(self, new_total: int = 1, missing_name: str | None = None) -> None:
        self.new_total = new_total
        self.missing_name = missing_name
        self.append_calls: list[tuple[str, list[dict[str, Any]]]] = []

    def list(self):
        return []

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return []

    def get_fields(self, name: str) -> list[str]:
        return []

    def get_rows_page(self, name: str, offset: int, limit: int):
        return [], 0

    def create(self, name: str, fields: list[str]) -> None:
        pass

    def create_from_csv_bytes(self, name: str, content: bytes) -> None:
        pass

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        if self.missing_name is not None and name == self.missing_name:
            raise FileNotFoundError(name)
        self.append_calls.append((name, rows))
        return self.new_total

    def delete(self, name: str) -> None:
        pass


class InMemoryDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self) -> None:
        self._by_name: dict[str, DatasetSummaryRecord] = {}

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._by_name[summary.dataset_name] = summary
        return summary

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        return self._by_name.get(dataset_name)

    def delete(self, dataset_name: str) -> None:
        self._by_name.pop(dataset_name, None)


class RecordingDatasetAnalysisDispatcher(DatasetAnalysisDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, dataset_name: str) -> None:
        self.dispatched.append(dataset_name)


class InMemoryFeedbackRepository(FeedbackRepository):
    def __init__(self) -> None:
        self.created: list[FeedbackRecord] = []

    def create(self, feedback: FeedbackRecord) -> FeedbackRecord:
        self.created.append(feedback)
        return feedback

    def get(self, feedback_id: UUID) -> FeedbackRecord | None:
        return next((f for f in self.created if f.id == feedback_id), None)

    def list(self, configuration_id=None, version=None) -> list[FeedbackRecord]:
        results = self.created
        if configuration_id is not None:
            results = [f for f in results if f.configuration_id == configuration_id]
        if version is not None:
            results = [f for f in results if f.version == version]
        return results


class InMemoryWorkflowExecutionRepository(WorkflowExecutionRepository):
    def __init__(self, executions: dict[UUID, WorkflowExecutionRecord] | None = None) -> None:
        self._by_id = executions or {}

    def create(self, workflow: WorkflowExecutionRecord) -> WorkflowExecutionRecord:
        self._by_id[workflow.id] = workflow
        return workflow

    def get(self, workflow_id: UUID) -> WorkflowExecutionRecord | None:
        return self._by_id.get(workflow_id)

    def update(self, workflow_id, **kwargs):
        return self._by_id.get(workflow_id)


def _alert(
    payload: dict[str, Any],
    workflow_execution_id: UUID | None = None,
    *,
    labels: dict[str, Any] | None = None,
) -> AlertRecord:
    now = datetime.now(timezone.utc)
    return AlertRecord(
        id=uuid4(),
        event_id="evt-1",
        event_type="transaction",
        status=AlertStatus.CLOSED,
        created_at=now,
        updated_at=now,
        workflow_execution_id=workflow_execution_id,
        schema_version=1,
        input=payload,
        labels=labels or {},
    )


def _execution(execution_id: UUID, configuration_ref: dict[str, Any] | None) -> WorkflowExecutionRecord:
    now = datetime.now(timezone.utc)
    return WorkflowExecutionRecord(
        id=execution_id,
        alert_id=uuid4(),
        async_operation_id=uuid4(),
        workflow_name="alert_review",
        status=WorkflowStatus.SUCCEEDED,
        input={"configuration_ref": configuration_ref} if configuration_ref else {},
        output=None,
        error=None,
        current_step=None,
        feedback_iterations=0,
        max_feedback_iterations=1,
        created_at=now,
        updated_at=now,
    )


def _make_use_case(
    *,
    alerts: InMemoryAlertRepository,
    datasets: FakeDatasetRepository,
    summaries: InMemoryDatasetSummaryRepository | None = None,
    dispatcher: RecordingDatasetAnalysisDispatcher | None = None,
    feedback: InMemoryFeedbackRepository | None = None,
    executions: InMemoryWorkflowExecutionRepository | None = None,
) -> tuple[CurateAlertToDatasetUseCase, InMemoryFeedbackRepository]:
    feedback = feedback or InMemoryFeedbackRepository()
    use_case = CurateAlertToDatasetUseCase(
        alert_repository=alerts,
        dataset_repository=datasets,
        summary_repository=summaries or InMemoryDatasetSummaryRepository(),
        dispatcher=dispatcher or RecordingDatasetAnalysisDispatcher(),
        feedback_repository=feedback,
        workflow_execution_repository=executions or InMemoryWorkflowExecutionRepository(),
    )
    return use_case, feedback


def test_curate_appends_canonical_input_labels_and_schema_version() -> None:
    alert = _alert({"eventId": "e-1", "object": {"triggeredRules": "RULE_A"}})
    alerts = InMemoryAlertRepository({alert.id: alert})
    datasets = FakeDatasetRepository(new_total=6)
    use_case, feedback = _make_use_case(alerts=alerts, datasets=datasets)

    output = use_case.execute(
        CurateAlertToDatasetInput(
            alert_id=alert.id,
            dataset_name="training_set",
            justification="Reviewed manually, clearly a training-worthy case.",
            configuration_id="cfg-1",
            version=3,
        )
    )

    assert output.dataset_name == "training_set"
    assert output.total_rows == 6
    assert output.status == DatasetAnalysisStatus.PENDING
    assert output.configuration_id == "cfg-1"
    assert output.version == 3
    assert datasets.append_calls == [
        (
            "training_set",
            [
                {
                    "eventId": "e-1",
                    "object": {"triggeredRules": "RULE_A"},
                    "schema_version": 1,
                }
            ],
        )
    ]

    assert len(feedback.created) == 1
    saved = feedback.created[0]
    assert saved.id == output.feedback_id
    assert saved.configuration_id == "cfg-1"
    assert saved.version == 3
    assert saved.alert_id == alert.id
    assert saved.dataset_name == "training_set"
    assert saved.justification == "Reviewed manually, clearly a training-worthy case."


def test_curate_keeps_labels_as_distinct_schema_field_columns() -> None:
    alert = _alert(
        {"eventId": "e-1", "channel": "GL"},
        labels={"fraud_label": "fraud"},
    )
    alerts = InMemoryAlertRepository({alert.id: alert})
    datasets = FakeDatasetRepository(new_total=1)
    use_case, _ = _make_use_case(alerts=alerts, datasets=datasets)

    use_case.execute(
        CurateAlertToDatasetInput(
            alert_id=alert.id,
            dataset_name="training_set",
            justification="Canonical labels should populate separate columns.",
            configuration_id="cfg-1",
            version=1,
        )
    )

    [(name, rows)] = datasets.append_calls
    assert name == "training_set"
    row = rows[0]
    assert row["fraud_label"] == "fraud"
    assert row["channel"] == "GL"
    assert row["eventId"] == "e-1"
    assert row["schema_version"] == 1


def test_curate_auto_detects_configuration_from_workflow_execution() -> None:
    execution_id = uuid4()
    alert = _alert({"eventId": "e-1"}, workflow_execution_id=execution_id)
    alerts = InMemoryAlertRepository({alert.id: alert})
    datasets = FakeDatasetRepository()
    executions = InMemoryWorkflowExecutionRepository(
        {execution_id: _execution(execution_id, {"configuration_id": "cfg-auto", "version": 7})}
    )
    use_case, feedback = _make_use_case(alerts=alerts, datasets=datasets, executions=executions)

    output = use_case.execute(
        CurateAlertToDatasetInput(
            alert_id=alert.id,
            dataset_name="training_set",
            justification="Auto-detected configuration from the test run.",
        )
    )

    assert output.configuration_id == "cfg-auto"
    assert output.version == 7
    assert feedback.created[0].configuration_id == "cfg-auto"
    assert feedback.created[0].version == 7


def test_curate_auto_detects_configuration_stored_on_the_alert() -> None:
    # A production alert: no configuration_ref on its execution, but the
    # workflow stored the configuration it resolved on the alert itself.
    execution_id = uuid4()
    alert = dataclasses.replace(
        _alert({"eventId": "e-1"}, workflow_execution_id=execution_id),
        configuration_id="cfg-active",
        configuration_version=3,
    )
    alerts = InMemoryAlertRepository({alert.id: alert})
    datasets = FakeDatasetRepository()
    executions = InMemoryWorkflowExecutionRepository(
        {execution_id: _execution(execution_id, None)}
    )
    use_case, feedback = _make_use_case(alerts=alerts, datasets=datasets, executions=executions)

    output = use_case.execute(
        CurateAlertToDatasetInput(
            alert_id=alert.id,
            dataset_name="training_set",
            justification="Production alert, configuration stored on it.",
        )
    )

    assert (output.configuration_id, output.version) == ("cfg-active", 3)
    assert (feedback.created[0].configuration_id, feedback.created[0].version) == ("cfg-active", 3)


def test_curate_raises_value_error_when_configuration_cannot_be_determined() -> None:
    alert = _alert({"eventId": "e-1"})  # no workflow_execution_id
    alerts = InMemoryAlertRepository({alert.id: alert})
    datasets = FakeDatasetRepository()
    use_case, feedback = _make_use_case(alerts=alerts, datasets=datasets)

    with pytest.raises(ValueError, match="selecciónala manualmente"):
        use_case.execute(
            CurateAlertToDatasetInput(
                alert_id=alert.id,
                dataset_name="training_set",
                justification="No configuration info available anywhere.",
            )
        )

    assert datasets.append_calls == []
    assert feedback.created == []


def test_curate_raises_lookup_error_when_alert_missing() -> None:
    alerts = InMemoryAlertRepository()
    datasets = FakeDatasetRepository()
    use_case, feedback = _make_use_case(alerts=alerts, datasets=datasets)

    with pytest.raises(LookupError):
        use_case.execute(
            CurateAlertToDatasetInput(
                alert_id=uuid4(),
                dataset_name="training_set",
                justification="Doesn't matter, alert doesn't exist.",
                configuration_id="cfg-1",
                version=1,
            )
        )

    assert datasets.append_calls == []
    assert feedback.created == []


def test_curate_propagates_file_not_found_when_dataset_missing() -> None:
    alert = _alert({"eventId": "e-1"})
    alerts = InMemoryAlertRepository({alert.id: alert})
    datasets = FakeDatasetRepository(missing_name="ghost")
    use_case, feedback = _make_use_case(alerts=alerts, datasets=datasets)

    with pytest.raises(FileNotFoundError):
        use_case.execute(
            CurateAlertToDatasetInput(
                alert_id=alert.id,
                dataset_name="ghost",
                justification="Dataset doesn't exist.",
                configuration_id="cfg-1",
                version=1,
            )
        )

    # Feedback must not be created for a curation that never actually landed.
    assert feedback.created == []
