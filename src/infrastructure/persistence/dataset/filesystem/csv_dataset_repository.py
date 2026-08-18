from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

from src.application.ports.dataset_port import DatasetRecord, DatasetRepository

# Python's default (131072 bytes) is too small for a single CSV field once
# a dataset embeds something like a customer's full transaction history as
# JSON in one column - real rows in this codebase's datasets have hit
# 280KB+ there. No dataset-specific reason to cap this at all.
csv.field_size_limit(sys.maxsize)


class FilesystemCsvDatasetRepository(DatasetRepository):
    def __init__(self, datasets_dir: Path) -> None:
        self._dir = datasets_dir

    def list(self) -> list[DatasetRecord]:
        if not self._dir.is_dir():
            return []
        records = []
        for path in sorted(self._dir.glob("*.csv")):
            with path.open(newline="", encoding="utf-8") as f:
                row_count = sum(1 for _ in csv.reader(f)) - 1  # minus header
            records.append(DatasetRecord(name=path.stem, row_count=max(row_count, 0)))
        return records

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        path = self._dir / f"{name}.csv"
        with path.open(newline="", encoding="utf-8") as f:
            return [_unflatten(row) for row in csv.DictReader(f)]


def _unflatten(row: dict[str, str]) -> dict[str, Any]:
    # pre_process_alert.py reads mandatory fields via dotted paths (e.g.
    # "object.triggeredRules", "amount.baseValue") - a flat CSV can supply
    # those as dotted column headers, so turn "a.b" -> {"a": {"b": ...}}
    # here rather than teaching the dataset adapter any ARIC-specific
    # field names.
    result: dict[str, Any] = {}
    for key, value in row.items():
        if not key:
            # A leading unnamed column - e.g. pandas' to_csv(index=True)
            # row-index artifact, seen in real exports - not alert data,
            # and DynamoDB rejects an empty attribute name outright.
            continue
        parts = key.split(".")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return result
