from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any

from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaRepository,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.simulation_scenario_port import FieldGenerator, GeneratorKind


class SeedSimulationFromDatasetUseCase:
    """Build reviewable generators from an active schema and dataset.

    Numeric selection is intentionally simple and stable: integer non-negative
    samples whose variance is within 50% of the larger of the mean and one use
    Poisson; otherwise,
    positive samples with mean noticeably above their median use log-normal;
    all remaining numeric samples use normal. Sensitive fields never copy a
    dataset value: they receive deliberately synthetic generators.
    """

    def __init__(
        self, datasets: DatasetRepository, schemas: AlertSchemaRepository
    ) -> None:
        self._datasets = datasets
        self._schemas = schemas

    def execute(self, dataset_name: str) -> dict[str, FieldGenerator]:
        schema = self._schemas.get_active()
        if schema is None:
            raise ValueError("No active alert schema is available")
        rows = self._datasets.get_rows(dataset_name)
        fields = [
            field
            for field in schema.fields
            if field.data_source == AlertSchemaDataSource.ARIC
            and field.is_alert
            and not field.is_label
            and field.field_ds_loc
        ]
        return {
            field.field_ds_loc: self._generator_for(field, rows)
            for field in fields
        }

    def _generator_for(
        self, field: AlertSchemaField, rows: list[dict[str, Any]]
    ) -> FieldGenerator:
        if field.is_sensible:
            return _synthetic_generator(field)

        values = [
            value
            for row in rows
            if (value := _read_value(row, field.field_ds_loc)) is not None
        ]
        if field.type == AlertSchemaFieldType.NUMBER:
            numeric = [_as_number(value) for value in values]
            numeric = [value for value in numeric if value is not None]
            return _numeric_generator(numeric)
        return FieldGenerator(
            kind=GeneratorKind.CATEGORICAL,
            weights={str(value): float(count) for value, count in Counter(values).items()},
        )


def _read_value(row: dict[str, Any], location: str) -> Any:
    if location in row:
        return row[location]
    current: Any = row
    for part in location.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _as_number(value: Any) -> float | None:
    if _is_number(value):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _numeric_generator(values: list[float]) -> FieldGenerator:
    if not values:
        return FieldGenerator(kind=GeneratorKind.NORMAL, params={"mu": 0.0, "sigma": 1.0})

    mean = statistics.fmean(values)
    variance = statistics.pvariance(values)
    is_count = all(value.is_integer() and value >= 0 for value in values)
    if is_count and abs(variance - mean) <= 0.5 * max(mean, 1.0):
        return FieldGenerator(kind=GeneratorKind.POISSON, params={"lambda": mean})

    if all(value > 0 for value in values):
        median = statistics.median(values)
        if mean > median * 1.1:
            logged = [math.log(value) for value in values]
            return FieldGenerator(
                kind=GeneratorKind.LOGNORMAL,
                params={"mu": statistics.fmean(logged), "sigma": statistics.pstdev(logged)},
            )

    return FieldGenerator(
        kind=GeneratorKind.NORMAL,
        params={"mu": mean, "sigma": statistics.pstdev(values)},
    )


def _synthetic_generator(field: AlertSchemaField) -> FieldGenerator:
    if field.type == AlertSchemaFieldType.NUMBER:
        return FieldGenerator(kind=GeneratorKind.NORMAL, params={"mu": 0.0, "sigma": 1.0})
    if field.type == AlertSchemaFieldType.BOOL:
        return FieldGenerator(
            kind=GeneratorKind.CATEGORICAL,
            weights={"true": 1.0, "false": 1.0},
        )
    return FieldGenerator(
        kind=GeneratorKind.CATEGORICAL,
        weights={f"synthetic_{field.field}_1": 1.0, f"synthetic_{field.field}_2": 1.0},
    )
