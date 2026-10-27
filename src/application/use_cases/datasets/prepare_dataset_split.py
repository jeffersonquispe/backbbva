from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.application.errors import ConflictError, ValidationError
from src.application.ports.alert_field_mapping_port import AlertFieldMappingRepository
from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_snapshot_port import DatasetSnapshotRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.datasets.create_mature_sample_snapshot import (
    PARTITION_METADATA_FIELD,
)
from src.domain.datasets.entities import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
)
from src.domain.datasets.mature_sample_entities import DatasetSnapshot
from src.domain.datasets.partitioning import (
    PARTITION_FIELD,
    PARTITION_NAMES,
    partition_rows,
    stratum_value,
)

DEFAULT_MAX_SPLIT_ROWS = 200_000
# Mature samples are retained in small numbers, so a bounded scan of the most
# recent snapshots is enough to recognise one of their datasets.
_SNAPSHOT_LOOKUP_LIMIT = 50
_MAX_REPORTED_STRATA = 50
_MAX_REPORTED_FIELDS = 10
_RESERVED_FINAL_PARTITION = "final"


class PrepareDatasetSplitUseCase:
    def __init__(
        self,
        datasets: DatasetRepository,
        summaries: DatasetSummaryRepository,
        clock: Clock | None = None,
        *,
        snapshots: DatasetSnapshotRepository | None = None,
        alert_schemas: AlertSchemaRepository | None = None,
        field_mappings: AlertFieldMappingRepository | None = None,
        max_rows: int = DEFAULT_MAX_SPLIT_ROWS,
    ) -> None:
        self._datasets = datasets
        self._summaries = summaries
        self._clock = resolve_clock(clock)
        self._snapshots = snapshots
        self._alert_schemas = alert_schemas
        self._field_mappings = field_mappings
        self._max_rows = max_rows

    def preview(
        self,
        *,
        source_name: str,
        proportions: dict[str, float],
        seed: int,
        stratify_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        prepared = self._partition(
            source_name=source_name,
            proportions=proportions,
            seed=seed,
            stratify_fields=stratify_fields,
        )
        return {
            "source_dataset_name": source_name,
            "source_content_sha256": prepared.content_hash,
            "source_row_count": len(prepared.rows),
            "partition_counts": prepared.partition_counts,
            "proportions": proportions,
            "seed": seed,
            "stratify_fields": list(prepared.stratify),
            "available_fields": prepared.fields,
            "strata_distribution": prepared.strata_distribution,
            "source_context": prepared.source_context,
            "schema_context": prepared.schema_context,
            "warnings": prepared.warnings,
        }

    def execute(
        self,
        *,
        source_name: str,
        target_name: str,
        proportions: dict[str, float],
        seed: int,
        stratify_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        if source_name == target_name:
            raise ValidationError("El dataset de particiones debe tener otro nombre")
        prepared = self._partition(
            source_name=source_name,
            proportions=proportions,
            seed=seed,
            stratify_fields=stratify_fields,
        )
        specification = {
            "source_name": source_name,
            "source_content_sha256": prepared.content_hash,
            "proportions": proportions,
            "seed": seed,
            "stratify_fields": list(prepared.stratify),
            "partition_field": PARTITION_FIELD,
        }
        snapshot_id = hashlib.sha256(
            json.dumps(specification, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        metadata = {
            **specification,
            "snapshot_id": snapshot_id,
            "partition_counts": prepared.partition_counts,
            "strata_distribution": prepared.strata_distribution,
            "source_context": prepared.source_context,
            "schema_context": prepared.schema_context,
            "warnings": prepared.warnings,
        }
        if target_name in {record.name for record in self._datasets.list()}:
            existing = self._summaries.get(target_name)
            if (
                existing
                and existing.split_metadata
                and existing.split_metadata.get("snapshot_id") == snapshot_id
            ):
                return _split_response(target_name, {**metadata, **existing.split_metadata})
            raise ConflictError("Ya existe un dataset con ese nombre")
        partitioned_rows = [
            row for name in PARTITION_NAMES for row in prepared.partitions[name]
        ]
        now = self._clock.now()
        self._datasets.create(target_name, [*prepared.fields, PARTITION_FIELD])
        try:
            self._datasets.append_rows(target_name, partitioned_rows)
        except Exception:
            self._datasets.delete(target_name)
            raise
        self._summaries.upsert(
            DatasetSummaryRecord(
                dataset_name=target_name,
                status=DatasetAnalysisStatus.READY,
                total_rows=len(partitioned_rows),
                available_fields=[*prepared.fields, PARTITION_FIELD],
                uploaded_at=now,
                updated_at=now,
                origin=DatasetOrigin.PARTITIONED,
                source_dataset_names=[source_name],
                split_metadata=metadata,
            )
        )
        return _split_response(target_name, metadata)

    def _partition(
        self,
        *,
        source_name: str,
        proportions: dict[str, float],
        seed: int,
        stratify_fields: list[str] | None,
    ) -> _PreparedSplit:
        known = next(
            (record for record in self._datasets.list() if record.name == source_name),
            None,
        )
        row_count = getattr(known, "row_count", None)
        if isinstance(row_count, int) and row_count > self._max_rows:
            raise ValidationError(_too_many_rows(row_count, self._max_rows))
        snapshot = self._mature_snapshot_for(source_name)
        if snapshot is not None and snapshot.dataset_refs.get(
            _RESERVED_FINAL_PARTITION
        ) == source_name:
            raise ValidationError(
                "La partición final de la muestra madura está reservada para la "
                "evaluación final y no se puede particionar"
            )
        rows = self._datasets.get_rows(source_name)
        if not rows:
            raise ValidationError("El dataset no tiene filas para particionar")
        if len(rows) > self._max_rows:
            raise ValidationError(_too_many_rows(len(rows), self._max_rows))
        fields = self._datasets.get_fields(source_name)
        sampler_partitions = Counter(
            str(row[PARTITION_METADATA_FIELD])
            for row in rows
            if PARTITION_METADATA_FIELD in row
        )
        if sampler_partitions[_RESERVED_FINAL_PARTITION]:
            raise ValidationError(
                "El dataset contiene filas de la partición final reservada; "
                "particiona sólo la muestra de diagnóstico"
            )
        if sampler_partitions:
            # The sampler's own assignment is replaced by the new split; the
            # column must not leak into the copy as a feature.
            rows = [
                {key: value for key, value in row.items() if key != PARTITION_METADATA_FIELD}
                for row in rows
            ]
            fields = [field for field in fields if field != PARTITION_METADATA_FIELD]
        stratify = tuple(dict.fromkeys(stratify_fields or []))
        unknown = set(stratify) - set(fields)
        if unknown:
            raise ValidationError(
                "Los campos de estratificación no existen: " + ", ".join(sorted(unknown))
            )
        try:
            partitions = partition_rows(
                rows,
                proportions=proportions,
                seed=seed,
                stratify_fields=stratify,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if any(not partitions[name] for name in PARTITION_NAMES):
            raise ValidationError(
                "La cantidad de filas no permite poblar todas las particiones; "
                "reduce los estratos o ajusta las proporciones"
            )
        content_hash = hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        source_context = self._source_context(source_name, snapshot, sampler_partitions)
        schema_context, warnings = self._schema_context(source_name, fields, snapshot)
        return _PreparedSplit(
            rows=rows,
            fields=fields,
            stratify=stratify,
            partitions=partitions,
            content_hash=content_hash,
            strata_distribution=_strata_distribution(partitions, stratify),
            source_context=source_context,
            schema_context=schema_context,
            warnings=warnings,
        )

    def _mature_snapshot_for(self, source_name: str) -> DatasetSnapshot | None:
        if self._snapshots is None:
            return None
        return next(
            (
                snapshot
                for snapshot in self._snapshots.list_recent(_SNAPSHOT_LOOKUP_LIMIT)
                if source_name in snapshot.dataset_refs.values()
            ),
            None,
        )

    def _source_context(
        self,
        source_name: str,
        snapshot: DatasetSnapshot | None,
        sampler_partitions: Counter[str],
    ) -> dict[str, Any]:
        if snapshot is not None:
            source_partition = next(
                name for name, ref in snapshot.dataset_refs.items() if ref == source_name
            )
            return {
                "kind": "mature_sample",
                "mature_snapshot_id": snapshot.snapshot_id,
                "mature_content_hash": snapshot.content_hash,
                "source_partition": source_partition,
                "period_start": snapshot.period_start.isoformat(),
                "period_end": snapshot.period_end.isoformat(),
                "maturing_days": snapshot.maturing_days,
                "excluded_partitions": [_RESERVED_FINAL_PARTITION],
                "sampler_partition_counts": dict(sorted(sampler_partitions.items())),
            }
        summary = self._summaries.get(source_name)
        origin = summary.origin if summary else DatasetOrigin.UPLOADED
        context: dict[str, Any] = {
            "kind": "catalog" if origin != DatasetOrigin.UPLOADED else "uploaded",
            "origin": origin.value,
        }
        if summary and summary.source_dataset_names:
            context["source_dataset_names"] = list(summary.source_dataset_names)
        return context

    def _schema_context(
        self,
        source_name: str,
        fields: list[str],
        snapshot: DatasetSnapshot | None,
    ) -> tuple[dict[str, Any], list[str]]:
        if self._alert_schemas is None:
            return {}, []
        active = self._alert_schemas.get_active()
        warnings: list[str] = []
        if active is None:
            return (
                {"active_version": None, "validated_versions": [], "compatible": False},
                ["No hay un esquema activo: la copia no se validó contra ningún esquema"],
            )
        mapping = self._field_mappings.get(source_name) if self._field_mappings else None
        if snapshot is not None:
            validated_versions = sorted(snapshot.schema_versions)
            context_kind = "mature_sample"
        elif mapping is not None:
            validated_versions = [mapping.schema_version]
            context_kind = "alert_field_mapping"
        else:
            validated_versions = [active.version]
            context_kind = "column_names"
        if active.version not in validated_versions:
            warnings.append(
                "La fuente corresponde al esquema "
                + ", ".join(f"v{version}" for version in validated_versions)
                + f" y el esquema activo es v{active.version}; revisa que los campos "
                "conserven su significado antes de comparar resultados"
            )
        present = set(fields)
        if mapping is not None:
            present.update(
                canonical
                for canonical, column in mapping.mappings.items()
                if column in fields
            )
        if snapshot is None:
            missing = sorted(
                field.field
                for field in active.fields
                if field.field
                and field.is_mandatory
                and field.is_alert
                and not field.is_sensible
                and not field.is_label
                and field.field not in present
            )
        else:
            # The sampler already validated its rows against the snapshot's
            # schema versions; only the version drift above is relevant.
            missing = []
        if missing:
            shown = ", ".join(missing[:_MAX_REPORTED_FIELDS])
            extra = len(missing) - _MAX_REPORTED_FIELDS
            warnings.append(
                f"Faltan {len(missing)} campos obligatorios del esquema v{active.version}: "
                + shown
                + (f" y {extra} más" if extra > 0 else "")
                + ". Mapea las columnas o úsala sólo para diagnóstico"
            )
        return (
            {
                "active_version": active.version,
                "validated_versions": validated_versions,
                "context": context_kind,
                "missing_mandatory_fields": missing,
                "compatible": not warnings,
            },
            warnings,
        )


@dataclass(frozen=True)
class _PreparedSplit:
    rows: list[dict[str, Any]]
    fields: list[str]
    stratify: tuple[str, ...]
    partitions: dict[str, list[dict[str, Any]]]
    content_hash: str
    strata_distribution: dict[str, dict[str, int]]
    source_context: dict[str, Any]
    schema_context: dict[str, Any]
    warnings: list[str]

    @property
    def partition_counts(self) -> dict[str, int]:
        return {name: len(self.partitions[name]) for name in PARTITION_NAMES}


def _split_response(target_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_name": target_name,
        "snapshot_id": metadata["snapshot_id"],
        "source_content_sha256": metadata["source_content_sha256"],
        "partition_field": PARTITION_FIELD,
        "partition_counts": metadata.get("partition_counts", {}),
        "proportions": metadata["proportions"],
        "seed": metadata["seed"],
        "stratify_fields": list(metadata["stratify_fields"]),
        "strata_distribution": metadata.get("strata_distribution", {}),
        "source_context": metadata.get("source_context", {}),
        "schema_context": metadata.get("schema_context", {}),
        "warnings": list(metadata.get("warnings", [])),
    }


def _strata_distribution(
    partitions: dict[str, list[dict[str, Any]]], stratify: tuple[str, ...]
) -> dict[str, dict[str, int]]:
    """Per-stratum counts for each partition; aggregates only, never rows."""
    if not stratify:
        return {}
    counts: dict[str, Counter[str]] = {}
    for name in PARTITION_NAMES:
        for row in partitions[name]:
            key = " | ".join(stratum_value(row, field) for field in stratify)
            counts.setdefault(key, Counter())[name] += 1
    ranked = sorted(counts, key=lambda key: (-sum(counts[key].values()), key))
    return {
        key: {name: counts[key][name] for name in PARTITION_NAMES}
        for key in ranked[:_MAX_REPORTED_STRATA]
    }


def _too_many_rows(rows: int, maximum: int) -> str:
    return (
        f"El dataset tiene {rows:,} filas y el máximo para particionar es {maximum:,}; "
        "extrae una muestra antes de particionar"
    )
