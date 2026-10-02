from __future__ import annotations

from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportDispatcher,
)
from src.infrastructure.entrypoint.worker.celery.tasks import (
    import_fraud_label_reviews_task,
)


class CeleryFraudLabelReviewImportDispatcher(FraudLabelReviewImportDispatcher):
    def dispatch(self, content_b64: str, reviewed_by: str) -> str:
        return import_fraud_label_reviews_task.delay(content_b64, reviewed_by).id
