from __future__ import annotations

from src.application.errors import ConflictError, NotFoundError
from src.application.ports.configuration_port import (
    ConfigurationRepository,
)
from src.application.ports.test_run_port import TestRunRepository, TestRunStatus
from src.domain.configurations.entities import (
    ConfigurationRecord,
)


class ConfigurationNotFoundError(NotFoundError):
    pass


class ConfigurationNotTestedError(ConflictError):
    pass


class ActivateConfigurationUseCase:
    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        test_run_repository: TestRunRepository,
    ) -> None:
        self._configurations = configuration_repository
        self._test_runs = test_run_repository

    def execute(self, configuration_id: str, version: int) -> ConfigurationRecord:
        if self._configurations.get(configuration_id, version) is None:
            raise ConfigurationNotFoundError(
                f"Configuration {configuration_id} v{version} not found"
            )

        if not self._has_succeeded_test_run(configuration_id, version):
            raise ConfigurationNotTestedError(
                f"Configuration {configuration_id} v{version} has not passed a "
                "test run in Testing"
            )

        return self._configurations.activate(configuration_id, version)

    def _has_succeeded_test_run(self, configuration_id: str, version: int) -> bool:
        return any(
            run.status == TestRunStatus.SUCCEEDED
            and run.config.configuration_ref is not None
            and run.config.configuration_ref.configuration_id == configuration_id
            and run.config.configuration_ref.version == version
            for run in self._test_runs.list()
        )
