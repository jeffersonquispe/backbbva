from __future__ import annotations

from collections import Counter
from typing import Any

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


def extract_fields(row: dict[str, Any]) -> dict[str, str | None]:
    extracted: dict[str, str | None] = {}
    for field_name in ANALYSIS_FIELDS:
        value: str | None = None
        for alias in _ALIASES[field_name]:
            raw = row.get(alias)
            if raw not in (None, ""):
                value = str(raw)
                break
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
        extracted = extract_fields(row)
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
