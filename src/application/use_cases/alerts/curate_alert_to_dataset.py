from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.application.dtos.alert_dtos import (
    CurateAlertToDatasetInput,
    CurateAlertToDatasetOutput,
)
from src.application.ports.alert_field_mapping_port import (
    AlertFieldMapping,
    AlertFieldMappingRepository,
)
from src.application.ports.alert_port import AlertRecord, AlertRepository
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import DatasetSummaryRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.feedback_port import FeedbackRecord, FeedbackRepository
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.use_cases.datasets.append_dataset_rows import (
    append_rows_and_dispatch,
)
from src.application.use_cases.datasets.field_extraction import get_nested_value


class CurateAlertToDatasetUseCase:
    """The analyst-facing "Al dataset" action: adds one alert's payload as a
    row in an existing training dataset, AND records structured Feedback
    about a configuration version - two distinct things that happen in the
    same click (confirmed with the end user). Feedback is owned by the
    configuration it's about, not by the dataset - dataset_name is kept on
    it only as a cross-reference, never the primary association.

    Row mapping: AlertRecord.payload is already the same dotted-header-
    derived nested-dict shape DatasetRepository's get_rows()/append_rows()
    use, so unmapped fields already pass through correctly for a dataset
    shaped like the raw payload. A per-dataset AlertFieldMapping (optional,
    admin-configured) additionally renames specific payload fields onto a
    dataset's real column names for datasets that don't share that raw
    shape (e.g. the ARIA reference CSV's snake_case columns) - applied on
    top of, not instead of, the existing pass-through/intersect behavior.
    """

    def __init__(
        self,
        alert_repository: AlertRepository,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
        mapping_repository: AlertFieldMappingRepository,
        feedback_repository: FeedbackRepository,
        workflow_execution_repository: WorkflowExecutionRepository,
    ) -> None:
        self._alerts = alert_repository
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher
        self._mappings = mapping_repository
        self._feedback = feedback_repository
        self._workflow_executions = workflow_execution_repository

    def execute(self, input: CurateAlertToDatasetInput) -> CurateAlertToDatasetOutput:
        alert = self._alerts.get(input.alert_id)
        if alert is None:
            raise LookupError(f"Alert '{input.alert_id}' not found")

        configuration_id, version = self._resolve_configuration(input, alert)

        mapping = self._mappings.get(input.dataset_name)
        row = _build_row(alert.payload, mapping)

        append_output = append_rows_and_dispatch(
            dataset_repository=self._datasets,
            summary_repository=self._summaries,
            dispatcher=self._dispatcher,
            name=input.dataset_name,
            rows=[row],
        )

        feedback = FeedbackRecord(
            id=uuid4(),
            configuration_id=configuration_id,
            version=version,
            alert_id=input.alert_id,
            justification=input.justification,
            dataset_name=input.dataset_name,
            created_at=datetime.now(timezone.utc),
        )
        self._feedback.create(feedback)

        return CurateAlertToDatasetOutput(
            dataset_name=append_output.name,
            total_rows=append_output.total_rows,
            status=append_output.status,
            feedback_id=feedback.id,
            configuration_id=configuration_id,
            version=version,
        )

    def _resolve_configuration(
        self, input: CurateAlertToDatasetInput, alert: AlertRecord
    ) -> tuple[str, int]:
        if input.configuration_id is not None and input.version is not None:
            return input.configuration_id, input.version

        # Auto-detect: only resolvable when the alert's workflow execution
        # pinned an explicit configuration_ref (e.g. it ran as part of a
        # test run - see start_alert_test_workflow.py). A real production
        # alert processed against "whatever's active" has no such record.
        if alert.workflow_execution_id is not None:
            execution = self._workflow_executions.get(alert.workflow_execution_id)
            if execution is not None:
                ref = execution.input.get("configuration_ref")
                if ref and ref.get("configuration_id") and ref.get("version") is not None:
                    return ref["configuration_id"], ref["version"]

        raise ValueError(
            "No se pudo determinar la configuración automáticamente; "
            "selecciónala manualmente."
        )


def _build_row(
    payload: dict[str, Any], mapping: AlertFieldMapping | None
) -> dict[str, Any]:
    row = dict(payload)
    if mapping is not None:
        for alert_field, dataset_column in mapping.mappings.items():
            value = get_nested_value(payload, alert_field)
            if value is not None:
                row[dataset_column] = value
    return row
