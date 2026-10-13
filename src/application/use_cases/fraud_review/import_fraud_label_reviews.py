"""Bulk fraud_label review from a CSV (decision D2) - runs in the worker.

Columns (header row required, any order, case-insensitive): alert_id,
fraud_label, note (note optional). ',' or ';' separated, UTF-8 (BOM ok).
Every row goes through ReviewFraudLabel (channel=csv), so each applied row
leaves its own audit row and rollup delta. An invalid row is reported and
skipped - it never aborts the batch. Only a file that can't be read at all
(bad encoding, missing columns, too many rows) fails as a whole."""

from __future__ import annotations

import csv
import io
from uuid import UUID

from src.application.dtos.fraud_review_dtos import ReviewFraudLabelInput
from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportResult,
    FraudLabelReviewImportStatus,
    FraudLabelReviewRowResult,
    FraudLabelReviewRowStatus,
)
from src.application.ports.fraud_label_review_port import FraudLabelReviewChannel
from src.application.use_cases.fraud_review.review_fraud_label import (
    ReviewFraudLabel,
    parse_fraud_label,
)
from src.domain.alerts.exceptions import AlertNotFoundError, InvalidFraudLabelError

REQUIRED_COLUMNS = ("alert_id", "fraud_label")
MAX_ROWS = 50_000


class InvalidFraudLabelReviewFileError(ValueError):
    pass


def _rows(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidFraudLabelReviewFileError("The file is not UTF-8 text") from exc
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    header = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise InvalidFraudLabelReviewFileError(
            "Missing column(s): "
            + ", ".join(missing)
            + " (expected header: alert_id,fraud_label,note)"
        )
    reader.fieldnames = header
    rows: list[dict[str, str]] = []
    for raw in reader:
        values = {
            key: (value or "").strip() if isinstance(value, str) else ""
            for key, value in raw.items()
            if key is not None
        }
        if not any(values.values()):
            continue  # blank line
        rows.append(values)
        if len(rows) > MAX_ROWS:
            raise InvalidFraudLabelReviewFileError(f"Too many rows (max {MAX_ROWS})")
    return rows


class ImportFraudLabelReviews:
    def __init__(self, review_fraud_label: ReviewFraudLabel) -> None:
        self._review = review_fraud_label

    def execute(self, content: bytes, reviewed_by: str) -> FraudLabelReviewImportResult:
        try:
            rows = _rows(content)
        except InvalidFraudLabelReviewFileError as exc:
            return FraudLabelReviewImportResult(
                status=FraudLabelReviewImportStatus.FAILED, error=str(exc)
            )
        results = [
            self._apply(number, row, reviewed_by)
            for number, row in enumerate(rows, start=1)
        ]
        applied = sum(
            1 for r in results if r.status == FraudLabelReviewRowStatus.APPLIED
        )
        return FraudLabelReviewImportResult(
            status=FraudLabelReviewImportStatus.READY,
            total=len(results),
            applied=applied,
            failed=len(results) - applied,
            rows=results,
        )

    def _apply(
        self, number: int, row: dict[str, str], reviewed_by: str
    ) -> FraudLabelReviewRowResult:
        alert_id = row.get("alert_id", "")
        label = row.get("fraud_label", "")

        def result(status: FraudLabelReviewRowStatus, error: str | None = None):
            return FraudLabelReviewRowResult(
                row=number,
                alert_id=alert_id,
                fraud_label=label,
                status=status,
                error=error,
            )

        try:
            alert_uuid = UUID(alert_id)
        except ValueError:
            return result(
                FraudLabelReviewRowStatus.INVALID, "alert_id is not a valid UUID"
            )
        try:
            parse_fraud_label(label)
        except InvalidFraudLabelError as exc:
            return result(FraudLabelReviewRowStatus.INVALID, str(exc))
        try:
            self._review.execute(
                ReviewFraudLabelInput(
                    alert_id=alert_uuid,
                    fraud_label=label,
                    reviewed_by=reviewed_by,
                    channel=FraudLabelReviewChannel.CSV,
                    note=row.get("note", ""),
                )
            )
        except AlertNotFoundError as exc:
            return result(FraudLabelReviewRowStatus.NOT_FOUND, str(exc))
        except Exception as exc:  # noqa: BLE001 - one bad row never aborts the batch
            return result(
                FraudLabelReviewRowStatus.ERROR, f"{type(exc).__name__}: {exc}"
            )
        return result(FraudLabelReviewRowStatus.APPLIED)
