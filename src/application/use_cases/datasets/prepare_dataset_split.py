from __future__ import annotations

import hashlib
import json
from typing import Any

from src.application.errors import ConflictError, ValidationError
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.runtime_defaults import resolve_clock
from src.domain.datasets.entities import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
)
from src.domain.datasets.partitioning import (
    PARTITION_FIELD,
    PARTITION_NAMES,
    partition_rows,
)


class PrepareDatasetSplitUseCase:
    def __init__(
        self,
        datasets: DatasetRepository,
        summaries: DatasetSummaryRepository,
        clock: Clock | None = None,
    ) -> None:
        self._datasets = datasets
        self._summaries = summaries
        self._clock = resolve_clock(clock)

    def preview(
        self,
        *,
        source_name: str,
        proportions: dict[str, float],
        seed: int,
        stratify_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        rows, fields, stratify, partitions = self._partition(
            source_name=source_name,
            proportions=proportions,
            seed=seed,
            stratify_fields=stratify_fields,
        )
        content_hash = hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        return {
            "source_dataset_name": source_name,
            "source_content_sha256": content_hash,
            "source_row_count": len(rows),
            "partition_counts": {name: len(partitions[name]) for name in PARTITION_NAMES},
            "proportions": proportions,
            "seed": seed,
            "stratify_fields": list(stratify),
            "available_fields": fields,
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
        rows, fields, stratify, partitions = self._partition(
            source_name=source_name,
            proportions=proportions,
            seed=seed,
            stratify_fields=stratify_fields,
        )

        content_hash = hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        specification = {
            "source_name": source_name,
            "source_content_sha256": content_hash,
            "proportions": proportions,
            "seed": seed,
            "stratify_fields": list(stratify),
            "partition_field": PARTITION_FIELD,
        }
        snapshot_id = hashlib.sha256(
            json.dumps(specification, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if target_name in {record.name for record in self._datasets.list()}:
            existing = self._summaries.get(target_name)
            if existing and existing.split_metadata:
                prior = existing.split_metadata
                if prior.get("snapshot_id") == snapshot_id:
                    return {
                        "dataset_name": target_name,
                        "snapshot_id": snapshot_id,
                        "source_content_sha256": content_hash,
                        "partition_field": PARTITION_FIELD,
                        "partition_counts": prior.get("partition_counts", {}),
                        "proportions": proportions,
                        "seed": seed,
                        "stratify_fields": list(stratify),
                    }
            raise ConflictError("Ya existe un dataset con ese nombre")
        partitioned_rows = [
            row for name in PARTITION_NAMES for row in partitions[name]
        ]
        now = self._clock.now()
        self._datasets.create(target_name, [*fields, PARTITION_FIELD])
        try:
            self._datasets.append_rows(target_name, partitioned_rows)
        except Exception:
            self._datasets.delete(target_name)
            raise
        metadata = {
            **specification,
            "snapshot_id": snapshot_id,
            "partition_counts": {name: len(partitions[name]) for name in PARTITION_NAMES},
        }
        self._summaries.upsert(
            DatasetSummaryRecord(
                dataset_name=target_name,
                status=DatasetAnalysisStatus.READY,
                total_rows=len(partitioned_rows),
                available_fields=[*fields, PARTITION_FIELD],
                uploaded_at=now,
                updated_at=now,
                origin=DatasetOrigin.PARTITIONED,
                source_dataset_names=[source_name],
                split_metadata=metadata,
            )
        )
        return {
            "dataset_name": target_name,
            "snapshot_id": snapshot_id,
            "source_content_sha256": content_hash,
            "partition_field": PARTITION_FIELD,
            "partition_counts": metadata["partition_counts"],
            "proportions": proportions,
            "seed": seed,
            "stratify_fields": list(stratify),
        }

    def _partition(
        self,
        *,
        source_name: str,
        proportions: dict[str, float],
        seed: int,
        stratify_fields: list[str] | None,
    ) -> tuple[list[dict[str, Any]], list[str], tuple[str, ...], dict[str, list[dict[str, Any]]]]:
        rows = self._datasets.get_rows(source_name)
        if not rows:
            raise ValidationError("El dataset no tiene filas para particionar")
        fields = self._datasets.get_fields(source_name)
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
        return rows, fields, stratify, partitions
