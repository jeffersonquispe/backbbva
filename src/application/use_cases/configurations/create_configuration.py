from __future__ import annotations

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.errors import ConfigurationWriteConflict, ConflictError
from src.application.ports.clock_port import Clock
from src.application.ports.configuration_port import (
    ConfigurationRepository,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.configurations.entities import (
    ConfigurationRecord,
)


class ConfigurationVersionConflictError(ConflictError):
    pass


class CreateConfigurationUseCase:
    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._configurations = configuration_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, input: CreateConfigurationInput) -> ConfigurationRecord:
        now = self._clock.now()
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
            version = latest.version + 1 if latest is not None else 1
        else:
            configuration_id = str(self._id_generator.new_id())
            version = 1

        record = ConfigurationRecord(
            configuration_id=configuration_id,
            version=version,
            name=input.name,
            description=input.description,
            active=False,
            general=input.general,
            infra=input.infra,
            test=input.test,
            created_at=now,
            updated_at=now,
            created_by=input.created_by,
            segments=input.segments,
        )
        try:
            return self._configurations.create(record)
        except ConfigurationWriteConflict as exc:
            raise ConfigurationVersionConflictError(
                f"Configuration {configuration_id} changed while this version was being saved; reload and retry"
            ) from exc
