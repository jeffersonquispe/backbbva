from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from enum import StrEnum


class FraudLabelReviewImportStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class FraudLabelReviewRowStatus(StrEnum):
    APPLIED = "applied"
    INVALID = "invalid"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass
class FraudLabelReviewRowResult:
    # 1-based data row number (header excluded).
    row: int
    alert_id: str
    fraud_label: str
    status: FraudLabelReviewRowStatus
    error: str | None = None


@dataclass
class FraudLabelReviewImportResult:
    status: FraudLabelReviewImportStatus
    total: int = 0
    applied: int = 0
    failed: int = 0
    rows: list[FraudLabelReviewRowResult] = field(default_factory=list)
    # Whole-file failure (unreadable CSV, missing columns, task crash).
    error: str | None = None


class FraudLabelReviewImportDispatcher(ABC):
    """Kicks off the async bulk CSV review (rows alert_id,fraud_label,note).
    Same shape as analyst_capacity_import_port.py: one-shot job whose
    per-row report only needs to reach the uploader once, so Celery's own
    result backend is the polling store (no repository). The durable record
    of every applied row is the fraud_label_reviews audit table. Adapter:
    infrastructure/queues/celery/fraud_label_review_import_dispatcher.py."""

    def dispatch(self, content_b64: str, reviewed_by: str) -> str:
        """Returns the task id to poll via FraudLabelReviewImportStatusReader."""
        raise NotImplementedError
