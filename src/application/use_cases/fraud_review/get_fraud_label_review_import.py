from __future__ import annotations

from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportResult,
)
from src.application.ports.fraud_label_review_import_status_reader_port import (
    FraudLabelReviewImportStatusReader,
)


class GetFraudLabelReviewImport:
    def __init__(self, reader: FraudLabelReviewImportStatusReader) -> None:
        self._reader = reader

    def execute(self, task_id: str) -> FraudLabelReviewImportResult:
        return self._reader.read(task_id)
