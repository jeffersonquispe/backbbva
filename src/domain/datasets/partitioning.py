from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

PARTITION_FIELD = "__aria_split_partition"
PARTITION_NAMES = ("training", "validation", "calibration", "test")


def partition_rows(
    rows: list[dict[str, Any]],
    *,
    proportions: dict[str, float],
    seed: int,
    stratify_fields: tuple[str, ...] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Create a stable, optionally stratified split without sharing rows."""
    if set(proportions) != set(PARTITION_NAMES):
        raise ValueError(f"Las particiones requeridas son: {', '.join(PARTITION_NAMES)}")
    if any(value <= 0 or value >= 1 for value in proportions.values()) or abs(
        sum(proportions.values()) - 1
    ) > 1e-9:
        raise ValueError("Las proporciones deben ser positivas y sumar 1")
    if len(rows) < len(PARTITION_NAMES) * 2:
        raise ValueError("Se necesitan al menos 8 filas para crear cuatro particiones")
    if any(PARTITION_FIELD in row for row in rows):
        raise ValueError("El dataset ya contiene el campo reservado de partición")

    groups: dict[tuple[str, ...], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, row in enumerate(rows):
        key = tuple(stratum_value(row, field) for field in stratify_fields)
        groups[key].append((index, row))

    result: dict[str, list[dict[str, Any]]] = {
        name: [] for name in PARTITION_NAMES
    }
    for key in sorted(groups):
        group = groups[key]
        ordered = sorted(
            group,
            key=lambda pair: hashlib.sha256(
                f"{seed}:{pair[0]}:{json.dumps(pair[1], sort_keys=True, default=str)}".encode()
            ).digest(),
        )
        sizes = _allocation(len(ordered), proportions)
        cursor = 0
        for name in PARTITION_NAMES:
            for _, row in ordered[cursor : cursor + sizes[name]]:
                result[name].append({**row, PARTITION_FIELD: name})
            cursor += sizes[name]

    for rows_in_partition in result.values():
        rows_in_partition.sort(
            key=lambda row: hashlib.sha256(
                f"{seed}:{json.dumps(row, sort_keys=True, default=str)}".encode()
            ).digest()
        )
    return result


def _allocation(size: int, proportions: dict[str, float]) -> dict[str, int]:
    raw = {name: size * proportions[name] for name in PARTITION_NAMES}
    counts = {name: int(raw[name]) for name in PARTITION_NAMES}
    remainder = size - sum(counts.values())
    ranked = sorted(PARTITION_NAMES, key=lambda name: (-(raw[name] - counts[name]), name))
    for name in ranked[:remainder]:
        counts[name] += 1
    return counts


def stratum_value(row: dict[str, Any], path: str) -> str:
    value: Any = row
    for part in path.split("."):
        if isinstance(value, list):
            value = value[0] if value else None
        value = value.get(part) if isinstance(value, dict) else None
    return str(value if value not in (None, "") else "unknown")
