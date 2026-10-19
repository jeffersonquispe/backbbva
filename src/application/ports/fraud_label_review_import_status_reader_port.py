from __future__ import annotations

from abc import ABC

from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportResult,
)


class FraudLabelReviewImportStatusReader(ABC):
    """Reads back a dispatched import's status/report by task id. Adapter:
    infrastructure/queues/celery/fraud_label_review_import_status_reader.py."""

    def read(self, task_id: str) -> FraudLabelReviewImportResult:
        raise NotImplementedError
