from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.ports.configuration_port import (
    ConfigurationRecord,
    ConfigurationRepository,
)
from src.application.ports.test_run_port import TestRunRepository


class ConfigurationVersionConflictError(Exception):
    pass


class CreateConfigurationUseCase:
    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        test_run_repository: TestRunRepository,
    ) -> None:
        self._test_runs = test_run_repository
        self._configurations = configuration_repository

    def execute(self, input: CreateConfigurationInput) -> ConfigurationRecord:
        now = datetime.now(UTC)
        overwrite = False
        if input.configuration_id is not None:
            latest = self._configurations.get_latest_version(input.configuration_id)
            if input.based_on_version is not None and (
                latest is None or latest.version != input.based_on_version
            ):
                latest_version = latest.version if latest is not None else None
                raise ConfigurationVersionConflictError(
                    f"Configuration {input.configuration_id} latest version is "
                    f"{latest_version}, but this draft was based on version "
                    f"{input.based_on_version}"
                )
            configuration_id = input.configuration_id
            # Overwrite the latest version in place instead of minting a new
            # one, as long as it never reached production - otherwise every
            # small tweak-and-save cycle piles up a fresh immutable version.
            # Once a version has ever been activated it's frozen for audit,
            # so the next save mints version+1 as before.
            overwrite = (
                latest is not None
                and input.based_on_version == latest.version
                and not latest.ever_tested
                and not latest.active
                and not latest.ever_activated
                and not any(
                    run.config.configuration_ref is not None
                    and run.config.configuration_ref.configuration_id
                    == configuration_id
                    and run.config.configuration_ref.version == latest.version
                    for run in self._test_runs.list()
                )
            )
            version = (
                latest.version
                if overwrite
                else (latest.version + 1 if latest is not None else 1)
            )
        else:
            configuration_id = str(uuid.uuid4())
            version = 1

        record = ConfigurationRecord(
            configuration_id=configuration_id,
            version=version,
            name=input.name,
            description=input.description,
            # Never active on creation - activation is a separate, explicit
            # step so the single-active invariant is only ever touched by
            # ActivateConfigurationUseCase.
            active=False,
            general=input.general,
            infra=input.infra,
            test=input.test,
            created_at=latest.created_at if overwrite else now,
            updated_at=now,
            created_by=input.created_by,
            segments=input.segments,
        )
        created = (
            self._configurations.update(record)
            if overwrite
            else self._configurations.create(record)
        )
        return created
