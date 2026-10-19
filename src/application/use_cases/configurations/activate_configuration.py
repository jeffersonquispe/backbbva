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
from src.domain.configurations.entities import (
    ConfigurationRecord,
)
from src.domain.test_runs.entities import TestRunStatus
from src.domain.workflows.entities import WorkflowStatus


class ConfigurationNotFoundError(NotFoundError):
    pass


class ConfigurationNotTestedError(ConflictError):
    pass


class ConfigurationActivationConflictError(ConflictError):
    pass


class ActivateConfigurationUseCase:
    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        test_run_repository: TestRunRepository,
        workflow_repository: WorkflowExecutionRepository | None = None,
    ) -> None:
        self._configurations = configuration_repository
        self._test_runs = test_run_repository
        self._workflows = workflow_repository

    def execute(
        self,
        configuration_id: str,
        version: int,
        expected_current: tuple[str, int] | None = None,
    ) -> ConfigurationRecord:
        if self._configurations.get(configuration_id, version) is None:
            raise ConfigurationNotFoundError(
                f"Configuration {configuration_id} v{version} not found"
            )

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
