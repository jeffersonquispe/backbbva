from __future__ import annotations

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


def _alert(payload: dict[str, Any]) -> AlertRecord:
    now = datetime.now(timezone.utc)
    return AlertRecord(
        id=uuid4(),
        event_id="evt-1",
        event_type="transaction",
        payload=payload,
        status=AlertStatus.CLOSED,
        created_at=now,
        updated_at=now,
    )


def test_curate_alert_to_dataset_appends_alert_payload_as_a_row() -> None:
    alert = _alert({"eventId": "e-1", "object": {"triggeredRules": "RULE_A"}})
    alerts = InMemoryAlertRepository({alert.id: alert})
    datasets = FakeDatasetRepository(new_total=6)
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = CurateAlertToDatasetUseCase(
        alert_repository=alerts,
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    output = use_case.execute(
        CurateAlertToDatasetInput(alert_id=alert.id, dataset_name="training_set")
    )

    assert output.name == "training_set"
    assert output.total_rows == 6
    assert output.status == DatasetAnalysisStatus.PENDING
    assert datasets.append_calls == [
        ("training_set", [{"eventId": "e-1", "object": {"triggeredRules": "RULE_A"}}])
    ]
    assert dispatcher.dispatched == ["training_set"]


def test_curate_alert_to_dataset_raises_lookup_error_when_alert_missing() -> None:
    alerts = InMemoryAlertRepository()
    datasets = FakeDatasetRepository()
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = CurateAlertToDatasetUseCase(
        alert_repository=alerts,
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    with pytest.raises(LookupError):
        use_case.execute(
            CurateAlertToDatasetInput(alert_id=uuid4(), dataset_name="training_set")
        )

    assert datasets.append_calls == []
    assert dispatcher.dispatched == []


def test_curate_alert_to_dataset_propagates_file_not_found_when_dataset_missing() -> None:
    alert = _alert({"eventId": "e-1"})
    alerts = InMemoryAlertRepository({alert.id: alert})
    datasets = FakeDatasetRepository(missing_name="ghost")
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = CurateAlertToDatasetUseCase(
        alert_repository=alerts,
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    with pytest.raises(FileNotFoundError):
        use_case.execute(
            CurateAlertToDatasetInput(alert_id=alert.id, dataset_name="ghost")
        )

    assert dispatcher.dispatched == []
