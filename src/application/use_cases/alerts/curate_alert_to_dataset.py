from __future__ import annotations

from typing import Any

from src.application.dtos.alert_dtos import (
    CurateAlertToDatasetInput,
    CurateAlertToDatasetOutput,
)
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import DatasetSummaryRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.feedback_port import FeedbackRecord, FeedbackRepository
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.application.use_cases.datasets.append_dataset_rows import (
    append_rows_and_dispatch,
)
from src.domain.alerts.entities import (
    AlertRecord,
)


class CurateAlertToDatasetUseCase:
    """The analyst-facing "Al dataset" action: adds one alert's payload as a
    row in an existing training dataset, AND records structured Feedback
    about a configuration version - two distinct things that happen in the
    same click (confirmed with the end user). Feedback is owned by the
    configuration it's about, not by the dataset - dataset_name is kept on
    it only as a cross-reference, never the primary association.

    Dataset rows are snapshots of the alert canonicalized by the active
    alert schema: input fields, label fields under their schema field names,
    and schema_version. AlertFieldMapping is deliberately not consulted here;
    it belongs only to export to an external dataset format.
    """

    def __init__(
        self,
        alert_repository: AlertRepository,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
        feedback_repository: FeedbackRepository,
        workflow_execution_repository: WorkflowExecutionRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._alerts = alert_repository
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher
        self._feedback = feedback_repository
        self._workflow_executions = workflow_execution_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, input: CurateAlertToDatasetInput) -> CurateAlertToDatasetOutput:
        alert = self._alerts.get(input.alert_id)
        if alert is None:
            raise LookupError(f"Alert '{input.alert_id}' not found")

        configuration_id, version = self._resolve_configuration(input, alert)

        row = _build_row(alert)

        append_output = append_rows_and_dispatch(
            dataset_repository=self._datasets,
            summary_repository=self._summaries,
            dispatcher=self._dispatcher,
            name=input.dataset_name,
            rows=[row],
            clock=self._clock,
        )

        feedback = FeedbackRecord(
            id=self._id_generator.new_id(),
            configuration_id=configuration_id,
            version=version,
            alert_id=input.alert_id,
            justification=input.justification,
            dataset_name=input.dataset_name,
            created_at=self._clock.now(),
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

        # Auto-detect: the configuration the workflow resolved for this
        # alert. Alerts processed before that was stored fall back to the
        # workflow execution's explicit configuration_ref (test runs only -
        # see start_alert_test_workflow.py).
        if (
            alert.configuration_id is not None
            and alert.configuration_version is not None
        ):
            return alert.configuration_id, alert.configuration_version
        if alert.workflow_execution_id is not None:
            execution = self._workflow_executions.get(alert.workflow_execution_id)
            if execution is not None:
                ref = execution.input.get("configuration_ref")
                if (
                    ref
                    and ref.get("configuration_id")
                    and ref.get("version") is not None
                ):
                    return ref["configuration_id"], ref["version"]

        raise ValueError(
            "No se pudo determinar la configuración automáticamente; "
            "selecciónala manualmente."
        )


def _build_row(alert: AlertRecord) -> dict[str, Any]:
    if alert.schema_version is None:
        raise ValueError("La alerta no tiene schema_version canónica")

    # Convention for E8 rows: input and labels share one flat dataset row;
    # label keys are their schema `field` names and must remain distinct from
    # input keys. The schema validation prevents a label/input collision.
    row = dict(alert.input)
    row.update(alert.labels)
    row["schema_version"] = alert.schema_version
    return row
