from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter
from datetime import timedelta
from typing import Any

from src.application.ports.alert_port import AlertRepository
from src.application.ports.alert_schema_port import (
    AlertSchemaFieldType,
    AlertSchemaRepository,
    AlertSchemaStatus,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_sampler_state_port import (
    DatasetSamplerStateRepository,
)
from src.application.ports.dataset_snapshot_port import (
    DatasetSnapshotRepository,
)
from src.application.ports.mature_sampler_schema_mapping_port import (
    MatureSamplerSchemaMappingRepository,
)
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.use_cases.datasets.preview_mature_sample import (
    _estimated_sample_size,
    _schema_mapping_is_configured,
    collect_mature_alerts,
)
from src.domain.datasets.mature_sample_entities import (
    DatasetSamplerState,
    DatasetSnapshot,
)
from src.domain.datasets.mature_sampling import (
    MatureSampleSpec,
    alert_field_value,
    content_hash,
    deterministic_partition,
    deterministic_sample,
    mapped_alert_label,
    stratum_key,
)

PARTITIONS = ("training", "validation", "test", "final")
PARTITION_METADATA_FIELD = "__aria_partition"
SAMPLE_TARGET_FIELD = "fraud_label"
MAX_ALERTS_PER_RUN = 100_000


class CreateMatureSampleSnapshotUseCase:
    def __init__(
        self,
        alerts: AlertRepository,
        alert_schemas: AlertSchemaRepository,
        operational_settings: OperationalSettingsRepository,
        sampler_settings: AssistantOptimizerSettingsPort,
        datasets: DatasetRepository,
        snapshots: DatasetSnapshotRepository,
        sampler_state: DatasetSamplerStateRepository,
        schema_mapping: MatureSamplerSchemaMappingRepository,
        clock: Clock,
    ) -> None:
        self._alerts = alerts
        self._alert_schemas = alert_schemas
        self._operational_settings = operational_settings
        self._sampler_settings = sampler_settings
        self._datasets = datasets
        self._snapshots = snapshots
        self._sampler_state = sampler_state
        self._schema_mapping = schema_mapping
        self._clock = clock

    def execute(self, *, trigger: str = "manual") -> DatasetSnapshot:
        settings = self._sampler_settings.get()
        schema_mapping = self._schema_mapping.get()
        if not _schema_mapping_is_configured(schema_mapping):
            raise ValueError(
                "Configura la marca inicial, sus fechas y la etiqueta vigente con su mapeo"
            )
        label_value_mapping = schema_mapping.label_value_mapping or {}
        operational = self._operational_settings.get()
        today = self._clock.now().date()
        maturity = operational.maturing_days
        period_end = today - timedelta(days=maturity)
        period_start = period_end - timedelta(days=settings.sampler_period_days - 1)
        schemas = self._selected_schema_versions(
            settings.sampler_compatible_schema_versions
        )
        schema_fields = [field for schema in schemas for field in schema.fields if field.is_alert and not field.is_sensible]
        if not any(
            field.field == schema_mapping.initial_mark_field
            and not field.is_label
            and field.type
            in {
                AlertSchemaFieldType.STRING,
                AlertSchemaFieldType.NUMBER,
                AlertSchemaFieldType.BOOL,
            }
            for field in schema_fields
        ):
            raise ValueError("La marca inicial no pertenece al esquema compatible")
        if not any(
            field.field == schema_mapping.initial_marking_date_field
            and field.type in {AlertSchemaFieldType.DATE, AlertSchemaFieldType.DATETIME}
            and not field.is_label
            for field in schema_fields
        ):
            raise ValueError("La fecha inicial no pertenece al esquema compatible")
        if not any(field.field == schema_mapping.target_field and field.is_label for field in schema_fields):
            raise ValueError("El campo objetivo no pertenece al esquema compatible")
        if not any(
            field.field == schema_mapping.marking_date_field
            and field.type in {AlertSchemaFieldType.DATE, AlertSchemaFieldType.DATETIME}
            and not field.is_label
            for field in schema_fields
        ):
            raise ValueError("La fecha de marcación no pertenece al esquema compatible")
        if schema_mapping.initial_marking_date_field == schema_mapping.marking_date_field:
            raise ValueError("Las fechas inicial y de última marcación deben ser distintas")
        fields = tuple(settings.sampler_strata)
        schema_pool = self._schema_field_pool(schemas)
        unsupported = set(fields) - set(schema_pool)
        if unsupported:
            raise ValueError(
                "Los campos de muestreo deben seleccionarse del esquema compatible: "
                + ", ".join(sorted(unsupported))
            )
        if not fields:
            raise ValueError("Selecciona al menos un campo del esquema para muestrear")
        if SAMPLE_TARGET_FIELD in fields or PARTITION_METADATA_FIELD in fields:
            raise ValueError("La selección contiene un campo reservado del muestreador")

        specification = {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "as_of": today.isoformat(),
            "maturing_days": maturity,
            "fields": list(fields),
            "initial_mark_field": schema_mapping.initial_mark_field,
            "initial_marking_date_field": schema_mapping.initial_marking_date_field,
            "target_field": schema_mapping.target_field,
            "marking_date_field": schema_mapping.marking_date_field,
            "label_value_mapping": dict(label_value_mapping),
            "schema_versions": [schema.version for schema in schemas],
            "sampler_period_days": settings.sampler_period_days,
            "sampler_minimum_per_stratum": settings.sampler_minimum_per_stratum,
            "sampler_fraud_oversampling_ratio": settings.sampler_fraud_oversampling_ratio,
            "sampler_train_proportion": settings.sampler_train_proportion,
            "sampler_validation_proportion": settings.sampler_validation_proportion,
            "sampler_test_proportion": settings.sampler_test_proportion,
            "sampler_error_margin_pct": settings.sampler_error_margin_pct,
            "sampler_confidence_pct": settings.sampler_confidence_pct,
            "sampler_seed_policy": settings.sampler_seed_policy,
        }
        snapshot_id = hashlib.sha256(
            json.dumps(specification, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:32]
        existing = self._snapshots.get(snapshot_id)
        if existing:
            self._save_sampler_state(existing, sum(existing.partition_counts.values()))
            self._apply_retention(settings.sampler_max_retained_samples)
            return existing

        seed = (
            int(snapshot_id[:16], 16)
            if settings.sampler_seed_policy == "fixed_per_sample"
            else secrets.randbits(64)
        )
        specification["seed"] = seed
        specification["trigger"] = trigger
        eligible = collect_mature_alerts(
            self._alerts,
            period_start=period_start,
            period_end=period_end,
            as_of=today,
            maturing_days=maturity,
            target_field=schema_mapping.target_field,
            marking_date_field=schema_mapping.marking_date_field,
            label_value_mapping=label_value_mapping,
            max_read=MAX_ALERTS_PER_RUN,
            limit_error="La ejecución supera el máximo de lectura por muestra",
        )
        allowed_versions = {schema.version for schema in schemas}
        eligible = [
            alert
            for alert in eligible
            if alert.schema_version in allowed_versions
        ]
        if not eligible:
            raise ValueError("No hay alertas maduras elegibles en el periodo")

        sample_size = _estimated_sample_size(settings, len(eligible))
        sample_spec = MatureSampleSpec(
            as_of=today,
            period_start=period_start,
            period_end=period_end,
            maturing_days=maturity,
            sample_size=sample_size,
            seed=seed,
            strata=fields,
            minimum_per_stratum=settings.sampler_minimum_per_stratum,
            fraud_oversampling_ratio=settings.sampler_fraud_oversampling_ratio,
            train_proportion=settings.sampler_train_proportion,
            validation_proportion=settings.sampler_validation_proportion,
            test_proportion=settings.sampler_test_proportion,
            target_field=schema_mapping.target_field,
            marking_date_field=schema_mapping.marking_date_field,
            label_value_mapping=label_value_mapping,
        )
        selected = deterministic_sample(eligible, sample_spec)
        rows_by_partition: dict[str, list[dict[str, Any]]] = {
            partition: [] for partition in PARTITIONS
        }
        for alert in selected:
            label = mapped_alert_label(
                alert,
                schema_mapping.target_field,
                label_value_mapping,
            ) or "pending"
            row: dict[str, Any] = {
                field: (alert.input or {}).get(field) for field in fields
            }
            row[schema_mapping.initial_mark_field] = alert_field_value(
                alert, schema_mapping.initial_mark_field
            )
            row[schema_mapping.initial_marking_date_field] = alert_field_value(
                alert, schema_mapping.initial_marking_date_field
            )
            row[SAMPLE_TARGET_FIELD] = label
            row[PARTITION_METADATA_FIELD] = deterministic_partition(
                str(alert.id), sample_spec
            )
            rows_by_partition[str(row[PARTITION_METADATA_FIELD])].append(row)

        partition_dataset_rows = {
            partition: [
                {key: value for key, value in row.items() if key != PARTITION_METADATA_FIELD}
                for row in rows
            ]
            for partition, rows in rows_by_partition.items()
        }
        hash_input: dict[str, list[dict[str, Any]]] = {
            **partition_dataset_rows,
            "all": [
                row
                for partition in PARTITIONS
                for row in rows_by_partition[partition]
            ],
        }
        strata_counts = Counter(
            " | ".join(stratum_key(alert, fields)) for alert in selected
        )
        partition_counts = {
            partition: len(rows) for partition, rows in rows_by_partition.items()
        }
        base_name = f"mature-sample-{snapshot_id}"
        dataset_refs = {
            **{name: f"{base_name}-{name}" for name in PARTITIONS},
            "all": base_name,
        }
        columns = list(
            dict.fromkeys(
                [
                    *fields,
                    schema_mapping.initial_mark_field,
                    schema_mapping.initial_marking_date_field,
                    SAMPLE_TARGET_FIELD,
                ]
            )
        )
        snapshot_persisted = False
        try:
            for partition in PARTITIONS:
                self._write_dataset(
                    dataset_refs[partition],
                    columns,
                    partition_dataset_rows[partition],
                )
            self._write_dataset(dataset_refs["all"], [*columns, PARTITION_METADATA_FIELD], [
                row for partition in PARTITIONS for row in rows_by_partition[partition]
            ])
            created_at = self._clock.now()
            snapshot = DatasetSnapshot(
                snapshot_id=snapshot_id,
                specification=specification,
                period_start=period_start,
                period_end=period_end,
                maturing_days=maturity,
                strata_counts=dict(sorted(strata_counts.items())),
                partition_counts=partition_counts,
                schema_versions=tuple(sorted(allowed_versions)),
                content_hash=content_hash(hash_input),
                trigger=trigger,
                dataset_refs=dataset_refs,
                created_at=created_at,
            )
            snapshot = self._snapshots.create(snapshot)
            snapshot_persisted = True
            self._save_sampler_state(snapshot, len(eligible))
            self._apply_retention(settings.sampler_max_retained_samples)
            return snapshot
        except Exception:
            if not snapshot_persisted:
                for dataset_name in dataset_refs.values():
                    try:
                        self._datasets.delete(dataset_name)
                    except FileNotFoundError:
                        pass
            raise

    def _save_sampler_state(self, snapshot: DatasetSnapshot, matured_count: int) -> None:
        self._sampler_state.update(
            DatasetSamplerState(
                state_id="current",
                last_snapshot_id=snapshot.snapshot_id,
                last_completed_at=snapshot.created_at,
                last_period_key=(
                    f"{snapshot.period_start.isoformat()}:{snapshot.period_end.isoformat()}"
                ),
                matured_alert_count=matured_count,
                latest_strata_counts=snapshot.strata_counts,
            )
        )

    def _apply_retention(self, maximum: int) -> None:
        for old in self._snapshots.list_recent(maximum + 1)[maximum:]:
            for dataset_name in old.dataset_refs.values():
                self._datasets.delete(dataset_name)
            self._snapshots.delete(old.snapshot_id)

    def _write_dataset(
        self, name: str, columns: list[str], rows: list[dict[str, Any]]
    ) -> None:
        try:
            self._datasets.delete(name)
        except FileNotFoundError:
            pass
        self._datasets.create(name, columns)
        if rows:
            self._datasets.append_rows(name, rows)

    def _selected_schema_versions(self, configured: tuple[str, ...]):
        versions = self._alert_schemas.list_versions()
        if configured:
            requested = {int(value) for value in configured}
            versions = [version for version in versions if version.version in requested]
        else:
            active = self._alert_schemas.get_active()
            versions = [active] if active else []
        selected = [
            version
            for version in versions
            if version is not None
            and version.status in {AlertSchemaStatus.ACTIVE, AlertSchemaStatus.HISTORICAL}
        ]
        if not selected:
            raise ValueError("No hay versiones de esquema compatibles seleccionadas")
        return selected

    @staticmethod
    def _schema_field_pool(schemas) -> set[str]:
        return {
            field.field
            for schema in schemas
            for field in schema.fields
            if field.field
            and field.is_alert
            and not field.is_sensible
            and not field.is_label
        }
