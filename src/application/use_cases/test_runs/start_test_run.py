from __future__ import annotations

import dataclasses

from src.application.dtos.alert_dtos import StartAlertWorkflowInput
from src.application.dtos.test_run_dtos import StartTestRunInput, StartTestRunOutput
from src.application.errors import NotFoundError, ValidationError
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.async_operation_port import AsyncOperationRepository
from src.application.ports.clock_port import Clock
from src.application.ports.configuration_port import (
    ConfigurationRepository,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.object_storage_port import ObjectStoragePort
from src.application.ports.test_run_port import (
    TestRunRepository,
)
from src.application.ports.workflow_executor_port import WorkflowExecutor
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.application.use_cases.test_runs.dataset_sampling import sample_rows
from src.application.use_cases.vector_store_instances.pin_configuration_vector_stores import (
    PinConfigurationVectorStoresUseCase,
)
from src.domain.alerts.entities import (
    AlertOrigin,
)
from src.domain.configurations.entities import (
    ConfigurationRef,
)
from src.domain.test_runs.entities import TestRunRecord, TestRunStatus


class StartTestRunUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        test_run_repository: TestRunRepository,
        alert_repository: AlertRepository,
        async_operation_repository: AsyncOperationRepository,
        workflow_repository: WorkflowExecutionRepository,
        workflow_executor: WorkflowExecutor,
        configuration_repository: ConfigurationRepository | None = None,
        metrics_recorder: RecordAlertMetricsEvent | None = None,
        schema_repository: AlertSchemaRepository | None = None,
        object_storage: ObjectStoragePort | None = None,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
        vector_store_pins: PinConfigurationVectorStoresUseCase | None = None,
    ) -> None:
        self._configurations = configuration_repository
        # A test must search the generation its version pins; one that is no
        # longer READY fails here instead of running silently without RAG.
        self._vector_store_pins = vector_store_pins
        self._schemas = schema_repository
        self._datasets = dataset_repository
        self._test_runs = test_run_repository
        # Reused as-is, not re-derived: this already builds the exact
        # alert/async-operation/workflow triad + dispatch a test case needs
        # (see start_alert_test_workflow.py) - a batch run is just that,
        # looped, with test_run_id/config_overrides threaded through.
        self._start_alert = StartAlertTestWorkflowUseCase(
            alert_repository=alert_repository,
            async_operation_repository=async_operation_repository,
            workflow_repository=workflow_repository,
            workflow_executor=workflow_executor,
            metrics_recorder=metrics_recorder,
            object_storage=object_storage,
        )
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, input: StartTestRunInput) -> StartTestRunOutput:
        if input.rows_override is not None and (
            input.sample_size is not None or input.sample_distribution is not None
        ):
            raise ValidationError("Optimizer replay rows cannot be sampled again")
        rows = (
            [dict(row) for row in input.rows_override]
            if input.rows_override is not None
            else self._datasets.get_rows(input.dataset_name)
        )
        if input.sample_distribution is not None and input.sample_size is None:
            raise ValidationError("sample_distribution requires sample_size")
        if input.sample_size is not None:
            rows = sample_rows(
                rows, size=input.sample_size, distribution=input.sample_distribution
            )
        if self._configurations is not None:
            ref = input.config.configuration_ref
            if ref is None:
                config = self._configurations.get_active()
            elif ref.version is None:
                config = self._configurations.get_latest_version(ref.configuration_id)
            else:
                config = self._configurations.get(ref.configuration_id, ref.version)
            if config is None and ref is not None:
                raise NotFoundError("Configuration version not found")
            if config is not None:
                if self._vector_store_pins is not None:
                    self._vector_store_pins.verify(config)
                self._configurations.mark_tested(
                    config.configuration_id, config.version
                )
                input.config = dataclasses.replace(
                    input.config,
                    configuration_ref=ConfigurationRef(
                        configuration_id=config.configuration_id,
                        version=config.version,
                    ),
                )
        if self._schemas is not None:
            active_schema = self._schemas.get_active()
            active_schema_version = active_schema.version if active_schema else None
            candidate_version = input.config.schema_version or active_schema_version
            if candidate_version is None:
                raise ValidationError(
                    "No active alert schema is available for this test run"
                )
            if (
                candidate_version is not None
                and self._schemas.get(candidate_version) is None
            ):
                raise NotFoundError("Alert schema version not found")
            if active_schema_version is not None:
                input.config = dataclasses.replace(
                    input.config,
                    schema_version=candidate_version,
                    active_schema_version=active_schema_version,
                )
        now = self._clock.now()
        test_run = self._test_runs.create(
            TestRunRecord(
                id=self._id_generator.new_id(),
                name=input.name,
                dataset_name=input.dataset_name,
                config=input.config,
                status=TestRunStatus.PENDING,
                total=len(rows),
                created_at=now,
                updated_at=now,
            )
        )
        # config_overrides only ever carries the per-step string patches
        # (_step_overrides in alert_review_workflow.py reads just
        # prompt_overrides/model_overrides from it) - configuration_ref is
        # a whole-config selection threaded separately below, not folded
        # into this blob.
        config_overrides = dataclasses.asdict(input.config)
        config_overrides.pop("configuration_ref", None)
        for row_index, row in enumerate(rows):
            self._start_alert.execute(
                StartAlertWorkflowInput(
                    payload=row,
                    test_run_id=test_run.id,
                    config_overrides=config_overrides,
                    max_feedback_iterations=input.config.max_feedback_iterations,
                    configuration_ref=input.config.configuration_ref,
                    schema_version=input.config.schema_version,
                    active_schema_version=input.config.active_schema_version,
                    origin=input.origin,
                    optimizer_row_index=(
                        row_index
                        if input.origin == AlertOrigin.OPTIMIZER_EVALUATION
                        else None
                    ),
                    optimizer_model_pin=input.optimizer_model_pin,
                    optimizer_component_pins=input.optimizer_component_pins,
                )
            )
        self._test_runs.update(test_run.id, status=TestRunStatus.RUNNING)
        return StartTestRunOutput(
            test_run_id=test_run.id,
            dispatched_count=len(rows),
        )
