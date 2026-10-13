from __future__ import annotations

from celery import states
from celery.result import AsyncResult

from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportResult,
    FraudLabelReviewImportStatus,
    FraudLabelReviewImportStatusReader,
    FraudLabelReviewRowResult,
    FraudLabelReviewRowStatus,
)
from src.infrastructure.queues.celery.app import app

_PENDING_STATES = {states.PENDING, states.RECEIVED, states.STARTED, states.RETRY}


def result_from_payload(payload: dict) -> FraudLabelReviewImportResult:
    return FraudLabelReviewImportResult(
        status=FraudLabelReviewImportStatus(payload["status"]),
        total=int(payload.get("total") or 0),
        applied=int(payload.get("applied") or 0),
        failed=int(payload.get("failed") or 0),
        error=payload.get("error"),
        rows=[
            FraudLabelReviewRowResult(
                row=int(row["row"]),
                alert_id=row.get("alert_id") or "",
                fraud_label=row.get("fraud_label") or "",
                status=FraudLabelReviewRowStatus(row["status"]),
                error=row.get("error"),
            )
            for row in payload.get("rows") or []
        ],
    )


class CeleryFraudLabelReviewImportStatusReader(FraudLabelReviewImportStatusReader):
    def read(self, task_id: str) -> FraudLabelReviewImportResult:
        result = AsyncResult(task_id, app=app)
        if result.state in _PENDING_STATES:
            return FraudLabelReviewImportResult(status=FraudLabelReviewImportStatus.PENDING)
        if result.state == states.SUCCESS:
            return result_from_payload(result.result)
        # FAILURE / REVOKED / unknown - a clear FAILED instead of a 500.
        return FraudLabelReviewImportResult(
            status=FraudLabelReviewImportStatus.FAILED,
            error=str(result.result) if result.result else result.state,
        )
