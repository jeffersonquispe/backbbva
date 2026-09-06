from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

# The 5 columns the dataset card analyzes. integration_point has multiple
# casings across the reference CSV export (integrationpoint) and the raw
# ARIC event shape (integrationPoint) - same alias set pre_process_alert.py's
# _MANDATORY_FIELD_PATHS uses for the same field.
ANALYSIS_FIELDS = (
    "razon_marcacion",
    "marcacion_final",
    "integration_point",
    "tipo",
    "triggered_rules",
)

_ALIASES: dict[str, tuple[str, ...]] = {
    "razon_marcacion": ("razon_marcacion",),
    "marcacion_final": ("marcacion_final",),
    "integration_point": ("integration_point", "integrationPoint", "integrationpoint"),
    "tipo": ("tipo",),
    "triggered_rules": ("triggered_rules", "triggeredRules"),
}

# razon_marcacion and triggered_rules carry multiple values per row, encoded
# as "[A, B, C]" (e.g. "[FR___ESTAFA, RECLAMO]",
# "[CUSTOMER - Score1000PSE, CUSTOMER - dg_score_1000]" - checked directly
# against Muestra_total_ARIA.csv). Counting the bracketed string as one
# atomic value would fragment the distribution across every combination
# instead of per individual reason/rule, so these two are split into their
# member values before counting (see compute_distributions below).
# marcacion_final/integration_point/tipo are always single-valued.
LIST_VALUED_FIELDS = frozenset({"razon_marcacion", "triggered_rules"})

UNKNOWN = "unknown"


def discover_fields(rows: list[dict[str, Any]]) -> list[str]:
    """Return every leaf field present in the dataset, preserving order.

    CSV headers containing dots are expanded by ``unflatten_row`` before this
    use case sees them. Walking nested mappings restores those fields as dotted
    paths, so the catalog works for both flat analytics exports and raw ARIC
    shaped datasets.
    """
    fields: list[str] = []
    seen: set[str] = set()

    def visit(value: Any, prefix: str = "") -> None:
        if not isinstance(value, dict):
            if prefix and prefix not in seen:
                seen.add(prefix)
                fields.append(prefix)
            return
        for key, child in value.items():
            if not key:
                continue
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(child, dict):
                visit(child, path)
            elif path not in seen:
                seen.add(path)
                fields.append(path)

    for row in rows:
        visit(row)
    return fields


def get_nested_value(row: dict[str, Any], field_name: str) -> str | None:
    """Look up a value by dotted path (e.g. "object.triggeredRules") in a
    row already unflattened by unflatten_row. Returns None for a missing
    path, a non-dict intermediate node, or an empty-string leaf. Used for
    any field outside the 5 special-cased ANALYSIS_FIELDS - arbitrary
    dataset columns don't get alias resolution or list-value splitting.
    """
    node: Any = row
    for part in field_name.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    if node in (None, ""):
        return None
    return str(node)


def extract_fields(
    row: dict[str, Any], fields: Iterable[str] = ANALYSIS_FIELDS
) -> dict[str, str | None]:
    extracted: dict[str, str | None] = {}
    for field_name in fields:
        if field_name in _ALIASES:
            value: str | None = None
            for alias in _ALIASES[field_name]:
                raw = row.get(alias)
                if raw not in (None, ""):
                    value = str(raw)
                    break
        else:
            value = get_nested_value(row, field_name)
        extracted[field_name] = value
    return extracted


def split_list_value(raw: str) -> list[str]:
    """"[A, B, C]" -> ["A", "B", "C"]; "[]"/"" -> []. A value with no
    brackets (defensive, in case a future export drops them) is treated as
    a single-item list rather than dropped."""
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip() for item in value.split(",") if item.strip()]


def compute_distributions(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...] = ANALYSIS_FIELDS,
) -> dict[str, dict[str, int]]:
    counters = {field_name: Counter() for field_name in fields}
    for row in rows:
        extracted = extract_fields(row, fields)
        for field_name in fields:
            value = extracted[field_name]
            if field_name in LIST_VALUED_FIELDS:
                items = split_list_value(value) if value else []
                if not items:
                    counters[field_name][UNKNOWN] += 1
                else:
                    # A row with multiple reasons/rules counts once toward
                    # each - counts (and the percentages derived from them
                    # in get_dataset_summary.py) can add up to more than
                    # total_rows/100% for these two fields, by design.
                    for item in items:
                        counters[field_name][item] += 1
            else:
                counters[field_name][value or UNKNOWN] += 1
    return {field_name: dict(counter) for field_name, counter in counters.items()}


def select_profiling_fields(
    rows: list[dict[str, Any]],
    available_fields: list[str],
    cardinality_limit: int = 50,
) -> tuple[str, ...]:
    """Pick which columns get a distribution computed for a given dataset.

    The 5 ANALYSIS_FIELDS are always kept, even when absent from
    ``available_fields`` entirely (e.g. an empty/extracted-style dataset) -
    the dataset card labels/reserves space for them regardless, for
    backward-compatible UI behavior. Beyond those, any other column in
    ``available_fields`` is added only if its distinct-value count across
    ``rows`` is at or under ``cardinality_limit`` - this keeps high-cardinality
    columns (ids, free text, timestamps, JSON blobs) out of the distribution
    view while letting genuinely categorical columns on non-ARIA-shaped
    datasets get profiled too.
    """
    selected: list[str] = list(ANALYSIS_FIELDS)
    selected_set = set(selected)
    for field_name in available_fields:
        if field_name in selected_set:
            continue
        distinct_values: set[str] = set()
        for row in rows:
            value = get_nested_value(row, field_name)
            if value is not None:
                distinct_values.add(value)
        if len(distinct_values) <= cardinality_limit:
            selected.append(field_name)
            selected_set.add(field_name)
    return tuple(selected)
