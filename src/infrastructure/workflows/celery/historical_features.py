"""Deterministic, row-local history aggregation shared by training and scoring."""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

from src.application.ports.model_port import HistoricalFeature


def read_field(row: dict[str, Any], path: str) -> Any:
    if path in row:
        return row[path]
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def timestamp(value: Any, timezone: str) -> pd.Timestamp:
    if value is None or value == "":
        raise ValueError("Falta una fecha requerida para el corte temporal")
    try:
        result = pd.Timestamp(value)
        if pd.isna(result):
            raise ValueError("Fecha ausente")
        if result.tzinfo is None:
            result = result.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
        return result.tz_convert("UTC")
    except Exception as exc:
        raise ValueError("Fecha inválida o ambigua; revisa el campo y la zona horaria") from exc


def _history(value: Any) -> list[dict] | None:
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, list):
            raise ValueError()
        records = [json.loads(v) if isinstance(v, str) else v for v in parsed]
        if any(not isinstance(v, dict) for v in records):
            raise ValueError()
        return records
    except (ValueError, TypeError) as exc:
        raise ValueError("El historial debe ser una lista JSON de objetos o textos JSON válidos") from exc


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def build_history_frame(rows: list[dict], recipes: list[HistoricalFeature], timezone: str) -> pd.DataFrame:
    output = []
    for row in rows:
        values = {}
        histories: dict[str, list[dict] | None] = {}
        dates: dict[tuple[str, str], list[pd.Timestamp]] = {}
        for recipe in recipes:
            if recipe.field not in histories:
                histories[recipe.field] = _history(read_field(row, recipe.field))
            entries = histories[recipe.field]
            name = f"history__{recipe.name}"
            if entries is None:
                values[name] = np.nan
                continue
            cutoff = timestamp(read_field(row, recipe.reference_field), timezone)
            date_key = (recipe.field, recipe.time_field)
            if date_key not in dates:
                dates[date_key] = [timestamp(read_field(e, recipe.time_field), timezone) for e in entries]
            included = [(e, t) for e, t in zip(entries, dates[date_key])
                        if cutoff - pd.Timedelta(hours=recipe.window_hours) <= t < cutoff
                        and (not recipe.filter_field or read_field(e, recipe.filter_field) == recipe.filter_value)]
            amounts = [v for e, _ in included if (v := _number(read_field(e, recipe.value_field))) is not None]
            if recipe.operation == "count":
                value = float(len(included))
            elif recipe.operation == "distinct":
                value = float(len({str(read_field(e, recipe.value_field)) for e, _ in included
                                   if read_field(e, recipe.value_field) not in (None, "")}))
            elif recipe.operation == "recency":
                value = (cutoff - max(t for _, t in included)).total_seconds() / 3600 if included else np.nan
            elif recipe.operation in ("sum", "mean", "median", "max"):
                value = float(getattr(np, recipe.operation)(amounts)) if amounts else np.nan
            else:
                raise ValueError("Agregación histórica no admitida")
            if recipe.compare_field:
                current = _number(read_field(row, recipe.compare_field))
                value = current / value if current is not None and math.isfinite(value) and value != 0 else np.nan
            values[name] = value
        output.append(values)
    return pd.DataFrame(output, index=range(len(rows)))
