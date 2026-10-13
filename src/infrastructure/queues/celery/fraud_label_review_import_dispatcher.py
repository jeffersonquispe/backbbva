from __future__ import annotations

from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportDispatcher,
)
from src.infrastructure.queues.celery.app import app

_TASK_NAME = "fraud_review.import_csv"


class CeleryFraudLabelReviewImportDispatcher(FraudLabelReviewImportDispatcher):
    def dispatch(self, content_b64: str, reviewed_by: str) -> str:
        return app.send_task(_TASK_NAME, args=[content_b64, reviewed_by]).id
