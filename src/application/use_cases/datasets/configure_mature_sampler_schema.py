from __future__ import annotations

from typing import Any

from src.application.errors import ValidationError
from src.application.ports.alert_schema_port import (
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaRepository,
    AlertSchemaStatus,
)
from src.application.ports.assistant_optimizer_settings_changes_port import (
    AssistantOptimizerSettingChange,
    AssistantOptimizerSettingsChange,
    AssistantOptimizerSettingsChangesPort,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.mature_sampler_schema_mapping_port import (
    MatureSamplerSchemaMappingRepository,
)
from src.application.runtime_defaults import DEFAULT_ID_GENERATOR, resolve_clock
from src.domain.datasets.mature_sample_entities import MatureSamplerSchemaMapping

FINAL_LABELS = {"fraud", "no_fraud"}
DATE_FIELD_TYPES = {AlertSchemaFieldType.DATE, AlertSchemaFieldType.DATETIME}
MARK_FIELD_TYPES = {
    AlertSchemaFieldType.STRING,
    AlertSchemaFieldType.NUMBER,
    AlertSchemaFieldType.BOOL,
}


class GetMatureSamplerSchemaConfigurationUseCase:
    def __init__(
        self,
        schemas: AlertSchemaRepository,
        sampler_settings: AssistantOptimizerSettingsPort,
        mappings: MatureSamplerSchemaMappingRepository,
    ) -> None:
        self._schemas = schemas
        self._sampler_settings = sampler_settings
        self._mappings = mappings

    def execute(self) -> dict[str, Any]:
        fields = _compatible_schema_fields(
            self._schemas,
            self._sampler_settings.get().sampler_compatible_schema_versions,
        )
        return {
            "initial_mark_fields": [
                _field_option(field)
                for field in fields
                if not field.is_label and field.type in MARK_FIELD_TYPES
            ],
            "initial_marking_date_fields": [
                _field_option(field)
                for field in fields
                if not field.is_label and field.type in DATE_FIELD_TYPES
            ],
            "target_fields": [_field_option(field) for field in fields if field.is_label],
            "marking_date_fields": [
                _field_option(field)
                for field in fields
                if not field.is_label and field.type in DATE_FIELD_TYPES
            ],
            "mapping": _mapping_payload(self._mappings.get()),
        }


class UpdateMatureSamplerSchemaConfigurationUseCase:
    def __init__(
        self,
        schemas: AlertSchemaRepository,
        sampler_settings: AssistantOptimizerSettingsPort,
        mappings: MatureSamplerSchemaMappingRepository,
        changes: AssistantOptimizerSettingsChangesPort,
        audit: AuditPort,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._schemas = schemas
        self._sampler_settings = sampler_settings
        self._mappings = mappings
        self._changes = changes
        self._audit = audit
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self, proposed: MatureSamplerSchemaMapping, *, changed_by: str
    ) -> MatureSamplerSchemaMapping:
        fields = _compatible_schema_fields(
            self._schemas,
            self._sampler_settings.get().sampler_compatible_schema_versions,
        )
        target_pool = {field.field for field in fields if field.is_label}
        initial_mark_pool = {
            field.field
            for field in fields
            if not field.is_label and field.type in MARK_FIELD_TYPES
        }
        date_pool = {
            field.field
            for field in fields
            if not field.is_label and field.type in DATE_FIELD_TYPES
        }
        raw_mapping = proposed.label_value_mapping or {}
        clearing = not any(
            (
                proposed.initial_mark_field,
                proposed.initial_marking_date_field,
                proposed.target_field,
                proposed.marking_date_field,
                raw_mapping,
            )
        )
        if not clearing:
            if proposed.initial_mark_field not in initial_mark_pool:
                raise ValidationError("La marca inicial debe pertenecer al esquema compatible")
            if proposed.initial_marking_date_field not in date_pool:
                raise ValidationError("La fecha inicial debe ser date/datetime del esquema compatible")
            if proposed.target_field not in target_pool:
                raise ValidationError("El campo objetivo debe ser una etiqueta del esquema compatible")
            if proposed.marking_date_field not in date_pool:
                raise ValidationError("La fecha de marcación debe ser date/datetime del esquema compatible")
            if proposed.initial_marking_date_field == proposed.marking_date_field:
                raise ValidationError("Las fechas inicial y de última marcación deben ser distintas")
        if len(raw_mapping) > 50 or (not clearing and not raw_mapping):
            raise ValidationError("Configura entre 1 y 50 valores de etiqueta")
        normalized: dict[str, str] = {}
        for raw_value, label in raw_mapping.items():
            key = normalize_label_value(raw_value)
            target = str(label).strip().lower()
            if not key or target not in FINAL_LABELS:
                raise ValidationError("Cada valor debe mapear a fraud o no_fraud")
            if key in normalized:
                raise ValidationError("El mapeo contiene valores de etiqueta duplicados")
            normalized[key] = target
        if not clearing and set(normalized.values()) != FINAL_LABELS:
            raise ValidationError("El mapeo debe incluir las clases fraud y no_fraud")
        updated_mapping = MatureSamplerSchemaMapping(
            initial_mark_field=proposed.initial_mark_field,
            initial_marking_date_field=proposed.initial_marking_date_field,
            target_field=proposed.target_field,
            marking_date_field=proposed.marking_date_field,
            label_value_mapping=normalized,
        )
        current = self._mappings.get()
        if _mapping_payload(current) == _mapping_payload(updated_mapping):
            return current
        self._mappings.update(updated_mapping)
        now = self._clock.now()
        change_id = str(self._id_generator.new_id())
        self._changes.append(
            AssistantOptimizerSettingsChange(
                id=change_id,
                changed_by=changed_by,
                changed_at=now,
                changes=[
                    AssistantOptimizerSettingChange(
                        path="sampler_schema_mapping",
                        previous=_mapping_payload(current),
                        new=_mapping_payload(updated_mapping),
                    )
                ],
            )
        )
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=changed_by,
                worker_name=None,
                action="mature_sampler.schema_mapping.update",
                entity_type="mature_sampler_schema_mapping",
                entity_id="current",
                correlation_id=change_id,
                parent_id=None,
                occurred_at=now,
                outcome="success",
            )
        )
        return updated_mapping


def _compatible_schema_fields(
    schemas: AlertSchemaRepository, compatible_versions: tuple[str, ...]
) -> list[AlertSchemaField]:
    versions = schemas.list_versions()
    if compatible_versions:
        requested = {int(version) for version in compatible_versions}
        versions = [version for version in versions if version.version in requested]
    else:
        active = schemas.get_active()
        versions = [active] if active else []
    return [
        field
        for version in versions
        if version is not None
        and version.status in {AlertSchemaStatus.ACTIVE, AlertSchemaStatus.HISTORICAL}
        for field in version.fields
        if field.is_alert and not field.is_sensible and field.field
    ]


def _field_option(field: AlertSchemaField) -> dict[str, str]:
    return {"field": field.field, "type": field.type.value, "description": field.description}


def _mapping_payload(mapping: MatureSamplerSchemaMapping) -> dict[str, Any]:
    return {
        "initial_mark_field": mapping.initial_mark_field,
        "initial_marking_date_field": mapping.initial_marking_date_field,
        "target_field": mapping.target_field,
        "marking_date_field": mapping.marking_date_field,
        "label_value_mapping": dict(mapping.label_value_mapping or {}),
    }


def normalize_label_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().casefold()
