from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.errors import ConfigurationWriteConflict, ConflictError
from src.application.ports.alert_schema_port import AlertSchemaRepository
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
    ConfigurationRef,
)


class ConfigurationVersionConflictError(ConflictError):
    pass


class ConfigurationMergeConflictError(ConfigurationVersionConflictError):
    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        super().__init__(
            "Concurrent configuration edits conflict at: " + ", ".join(paths)
        )


def _merge_value(
    base: Any, latest: Any, proposed: Any, path: str
) -> tuple[Any, list[str]]:
    """Three-way merge immutable leaves and independent nested fields."""
    if proposed == base:
        return latest, []
    if latest == base or proposed == latest:
        return proposed, []

    if (
        isinstance(base, dict)
        and isinstance(latest, dict)
        and isinstance(proposed, dict)
    ):
        merged: dict[Any, Any] = {}
        dict_conflicts: list[str] = []
        for key in base.keys() | latest.keys() | proposed.keys():
            child_path = f"{path}.{key}" if path else str(key)
            in_base, in_latest, in_proposed = (
                key in base,
                key in latest,
                key in proposed,
            )
            if not in_base:
                if in_latest and in_proposed:
                    value, child_conflicts = _merge_value(
                        None, latest[key], proposed[key], child_path
                    )
                    merged[key] = value
                    dict_conflicts.extend(child_conflicts)
                elif in_latest:
                    merged[key] = latest[key]
                elif in_proposed:
                    merged[key] = proposed[key]
            elif not in_latest or not in_proposed:
                # A deletion conflicts with a concurrent modification.
                if not in_latest and not in_proposed:
                    continue
                survivor = proposed.get(key) if in_proposed else latest.get(key)
                changed = survivor != base[key]
                if changed:
                    dict_conflicts.append(child_path)
            else:
                value, child_conflicts = _merge_value(
                    base[key], latest[key], proposed[key], child_path
                )
                merged[key] = value
                dict_conflicts.extend(child_conflicts)
        return merged, dict_conflicts

    if is_dataclass(base) and type(base) is type(latest) is type(proposed):
        updates: dict[str, Any] = {}
        record_conflicts: list[str] = []
        for item in fields(base):
            field_path = f"{path}.{item.name}" if path else item.name
            value, child_conflicts = _merge_value(
                getattr(base, item.name),
                getattr(latest, item.name),
                getattr(proposed, item.name),
                field_path,
            )
            updates[item.name] = value
            record_conflicts.extend(child_conflicts)
        return replace(latest, **updates), record_conflicts

    # Lists and scalar values are atomic. We only merge them when one side
    # retained the base value; otherwise the same setting was edited twice.
    return latest, [path]


def merge_stale_configuration(
    input: CreateConfigurationInput, repository: ConfigurationRepository
) -> tuple[CreateConfigurationInput, ConfigurationRecord | None]:
    """Merge a stale editor snapshot onto the current version when safe."""
    if input.configuration_id is None:
        return input, None
    latest = repository.get_latest_version(input.configuration_id)
    if input.based_on_version is None or latest is None:
        return input, latest
    if latest.version == input.based_on_version:
        return input, latest
    base = repository.get(input.configuration_id, input.based_on_version)
    if base is None:
        raise ConfigurationVersionConflictError(
            f"Base configuration {input.configuration_id}:v{input.based_on_version} no longer exists"
        )
    merged: dict[str, Any] = {}
    conflicts: list[str] = []
    for name in ("name", "description", "general", "infra", "test", "segments"):
        value, field_conflicts = _merge_value(
            getattr(base, name), getattr(latest, name), getattr(input, name), name
        )
        merged[name] = value
        conflicts.extend(field_conflicts)
    if conflicts:
        raise ConfigurationMergeConflictError(sorted(set(conflicts)))
    return replace(input, **merged, based_on_version=latest.version), latest


class CreateConfigurationUseCase:
    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
        schema_repository: AlertSchemaRepository | None = None,
    ) -> None:
        self._configurations = configuration_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR
        self._schemas = schema_repository

    def execute(self, input: CreateConfigurationInput) -> ConfigurationRecord:
        now = self._clock.now()
        if input.configuration_id is not None:
            configuration_id = input.configuration_id
            input, latest = merge_stale_configuration(input, self._configurations)
            if input.based_on_version is not None and (
                latest is None or latest.version != input.based_on_version
            ):
                latest_version = latest.version if latest is not None else None
                raise ConfigurationVersionConflictError(
                    f"Configuration {configuration_id} latest version is "
                    f"{latest_version}, but this draft was based on version "
                    f"{input.based_on_version}"
                )
            version = latest.version + 1 if latest is not None else 1
            parent_ref = (
                ConfigurationRef(configuration_id, latest.version)
                if latest is not None
                else None
            )
        else:
            configuration_id = str(self._id_generator.new_id())
            version = 1
            parent_ref = input.parent_ref
            if parent_ref is not None:
                if (
                    parent_ref.version is None
                    or self._configurations.get(
                        parent_ref.configuration_id, parent_ref.version
                    )
                    is None
                ):
                    raise ConfigurationVersionConflictError(
                        "Parent configuration version does not exist"
                    )

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
            schema_version_at_creation=(
                schema.version
                if self._schemas is not None
                and (schema := self._schemas.get_active()) is not None
                else None
            ),
            parent_ref=parent_ref,
            segments=input.segments,
        )
        try:
            return self._configurations.create(record)
        except ConfigurationWriteConflict as exc:
            raise ConfigurationVersionConflictError(
                f"Configuration {configuration_id} changed while this version was being saved; reload and retry"
            ) from exc
