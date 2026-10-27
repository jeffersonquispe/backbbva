from __future__ import annotations

from src.application.errors import (
    ConfigurationWriteConflict,
    ConflictError,
    NotFoundError,
)
from src.application.ports.configuration_port import (
    ConfigurationRepository,
)
from src.application.ports.test_run_port import TestRunRepository
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    VectorStoreGenerationUnavailableError,
)
from src.application.use_cases.vector_store_instances.pin_configuration_vector_stores import (
    PinConfigurationVectorStoresUseCase,
)
from src.domain.configurations.entities import (
    ConfigurationRecord,
)
from src.domain.fraud_knowledge.vector_store_generations import (
    configuration_vector_store_pins,
)
from src.domain.test_runs.entities import TestRunStatus
from src.domain.workflows.entities import WorkflowStatus


class ConfigurationNotFoundError(NotFoundError):
    pass


class ConfigurationNotTestedError(ConflictError):
    pass


class ConfigurationActivationConflictError(ConflictError):
    pass


class ConfigurationVectorStoreUnavailableError(ConflictError):
    pass


class VectorStorePublicationRequiresApprovalError(ConflictError):
    """The version searches different vector-store generations than the
    active one: only an approved deploy request may publish them."""


class ActivateConfigurationUseCase:
    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        test_run_repository: TestRunRepository,
        workflow_repository: WorkflowExecutionRepository | None = None,
        vector_store_pins: PinConfigurationVectorStoresUseCase | None = None,
    ) -> None:
        self._configurations = configuration_repository
        self._test_runs = test_run_repository
        self._workflows = workflow_repository
        self._vector_store_pins = vector_store_pins

    def execute(
        self,
        configuration_id: str,
        version: int,
        expected_current: tuple[str, int] | None = None,
        *,
        approved_deploy_request: bool = False,
    ) -> ConfigurationRecord:
        configuration = self._configurations.get(configuration_id, version)
        if configuration is None:
            raise ConfigurationNotFoundError(
                f"Configuration {configuration_id} v{version} not found"
            )
        if not approved_deploy_request:
            active = self._configurations.get_active()
            if configuration_vector_store_pins(configuration) != (
                configuration_vector_store_pins(active) if active else set()
            ):
                raise VectorStorePublicationRequiresApprovalError(
                    "Vector-store generation changes require an approved "
                    "configuration deploy request"
                )
        if self._vector_store_pins is not None:
            try:
                self._vector_store_pins.verify(configuration)
            except VectorStoreGenerationUnavailableError as exc:
                raise ConfigurationVectorStoreUnavailableError(str(exc)) from exc

        if not self._has_succeeded_test_run(configuration_id, version):
            raise ConfigurationNotTestedError(
                f"Configuration {configuration_id} v{version} has not passed a "
                "test run in Testing"
            )

        try:
            return self._configurations.activate(
                configuration_id, version, expected_current=expected_current
            )
        except ConfigurationWriteConflict as exc:
            raise ConfigurationActivationConflictError(str(exc)) from exc

    def _has_succeeded_test_run(self, configuration_id: str, version: int) -> bool:
        for run in self._test_runs.list():
            ref = run.config.configuration_ref
            if (
                ref is None
                or ref.configuration_id != configuration_id
                or ref.version != version
            ):
                continue
            if self._workflows is None:
                if run.status == TestRunStatus.SUCCEEDED:
                    return True
                continue

            workflows = self._workflows.list_by_test_run(run.id)
            if any(
                workflow.status
                in {
                    WorkflowStatus.PENDING,
                    WorkflowStatus.RUNNING,
                    WorkflowStatus.DISPATCHED,
                }
                for workflow in workflows
            ):
                continue
            if len(workflows) == run.total:
                return True
        return False
