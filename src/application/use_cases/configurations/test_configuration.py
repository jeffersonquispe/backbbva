from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.application.dtos.configuration_dtos import (
    ConfigurationChange,
    ConfigurationPreviewOutput,
    CreateConfigurationInput,
)
from src.application.errors import NotFoundError
from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.configuration_port import (
    ConfigurationRepository,
)
from src.application.use_cases.configurations.create_configuration import (
    ConfigurationVersionConflictError,
    merge_stale_configuration,
)
from src.domain.configurations.entities import (
    ConfigurationRecord,
)


class ConfigurationBaseNotFoundError(NotFoundError):
    pass


HIGH_IMPACT_WARNING = (
    "Los cambios en el estado del agente, infraestructura u operación pueden "
    "modificar considerablemente la operación, alterar su funcionamiento o bloquearlo."
)
SCHEMA_VERSION_WARNING = (
    "Esta configuración se creó con el esquema de alertas v{created}; "
    "la prueba usa el esquema activo v{active}. Verifica que sus campos y "
    "reglas sigan siendo compatibles."
)


class PreviewConfigurationUseCase:
    """Compare a proposed configuration without persisting it."""

    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        schema_repository: AlertSchemaRepository | None = None,
    ) -> None:
        self._configurations = configuration_repository
        self._schemas = schema_repository

    def execute(self, input: CreateConfigurationInput) -> ConfigurationPreviewOutput:
        input, _ = merge_stale_configuration(input, self._configurations)
        baseline = self._resolve_baseline(input)
        previous = _record_values(baseline) if baseline is not None else {}
        proposed = _input_values(input)
        changes = _diff(previous, proposed)
        warnings = (
            [HIGH_IMPACT_WARNING]
            if any(_is_high_impact(change.path) for change in changes)
            else []
        )
        if (
            baseline is not None
            and baseline.schema_version_at_creation is not None
            and self._schemas is not None
        ):
            active_schema = self._schemas.get_active()
            if (
                active_schema is not None
                and active_schema.version != baseline.schema_version_at_creation
            ):
                warnings.append(
                    SCHEMA_VERSION_WARNING.format(
                        created=baseline.schema_version_at_creation,
                        active=active_schema.version,
                    )
                )
        return ConfigurationPreviewOutput(changes=changes, warnings=warnings)

    def _resolve_baseline(
        self, input: CreateConfigurationInput
    ) -> ConfigurationRecord | None:
        if input.configuration_id is None:
            return None

        latest = self._configurations.get_latest_version(input.configuration_id)
        if latest is None:
            raise ConfigurationBaseNotFoundError(
                f"Configuration {input.configuration_id} not found"
            )
        if (
            input.based_on_version is not None
            and latest.version != input.based_on_version
        ):
            raise ConfigurationVersionConflictError(
                f"Configuration {input.configuration_id} latest version is "
                f"{latest.version}, but this draft was based on version "
                f"{input.based_on_version}"
            )
        return latest


def _record_values(record: ConfigurationRecord) -> dict[str, Any]:
    return {
        "name": record.name,
        "description": record.description,
        "general": asdict(record.general),
        "infra": asdict(record.infra),
        "test": asdict(record.test),
        "segments": {code: asdict(value) for code, value in record.segments.items()},
    }


def _input_values(input: CreateConfigurationInput) -> dict[str, Any]:
    return {
        "name": input.name,
        "description": input.description,
        "general": asdict(input.general),
        "infra": asdict(input.infra),
        "test": asdict(input.test),
        "segments": {code: asdict(value) for code, value in input.segments.items()},
    }


def _diff(previous: Any, proposed: Any, path: str = "") -> list[ConfigurationChange]:
    if isinstance(previous, dict) and isinstance(proposed, dict):
        changes: list[ConfigurationChange] = []
        for key in sorted(previous.keys() | proposed.keys()):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in previous:
                if isinstance(proposed[key], dict):
                    changes.extend(_diff({}, proposed[key], child_path))
                else:
                    changes.append(ConfigurationChange(child_path, None, proposed[key]))
            elif key not in proposed:
                if isinstance(previous[key], dict):
                    changes.extend(_diff(previous[key], {}, child_path))
                else:
                    changes.append(ConfigurationChange(child_path, previous[key], None))
            else:
                changes.extend(_diff(previous[key], proposed[key], child_path))
        return changes
    if previous != proposed:
        return [ConfigurationChange(path, previous, proposed)]
    return []


def _is_high_impact(path: str) -> bool:
    return (
        path == "infra"
        or path.startswith("infra.")
        or path.endswith(".agent")
        or ".agent." in path
    )
