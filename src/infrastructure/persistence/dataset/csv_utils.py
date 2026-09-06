from __future__ import annotations

import csv
import sys
from typing import Any

# Python's default (131072 bytes) is too small for a single CSV field once a
# dataset embeds something like a customer's full transaction history as
# JSON in one column - real rows in this codebase's datasets have hit 280KB+
# there. No dataset-specific reason to cap this at all.
csv.field_size_limit(sys.maxsize)


def unflatten_row(row: dict[str, str]) -> dict[str, Any]:
    # pre_process_alert.py reads mandatory fields via dotted paths (e.g.
    # "object.triggeredRules", "amount.baseValue") - a flat CSV can supply
    # those as dotted column headers, so turn "a.b" -> {"a": {"b": ...}}
    # here rather than teaching the dataset adapter any ARIC-specific field
    # names.
    result: dict[str, Any] = {}
    for key, value in row.items():
        if not key:
            # A leading unnamed column - e.g. pandas' to_csv(index=True)
            # row-index artifact, seen in real exports - not alert data, and
            # DynamoDB rejects an empty attribute name outright.
            continue
        parts = key.split(".")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return result


def flatten_row(row: dict[str, Any], _prefix: str = "") -> dict[str, str]:
    """Inverse of unflatten_row: {"a": {"b": 1}} -> {"a.b": "1"}. Used when
    writing rows back to CSV (append_rows/create) so nested values produced
    by get_rows' unflatten round-trip through the same dotted-header shape
    already on disk.
    """
    result: dict[str, str] = {}
    for key, value in row.items():
        full_key = f"{_prefix}{key}"
        if isinstance(value, dict):
            result.update(flatten_row(value, f"{full_key}."))
        else:
            result[full_key] = "" if value is None else str(value)
    return result
