"""Fraud history + fraud_label review (A3 / C5) wiring for the API."""
from __future__ import annotations

from functools import lru_cache

from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportDispatcher,
    FraudLabelReviewImportStatusReader,
)
from src.application.use_cases.alerts.list_alert_history import ListAlertHistory
from src.application.use_cases.fraud_review.get_fraud_label_review_import import (
    GetFraudLabelReviewImport,
)
from src.application.use_cases.fraud_review.list_fraud_label_reviews import (
    ListFraudLabelReviews,
)
from src.application.use_cases.fraud_review.review_fraud_label import ReviewFraudLabel
from src.application.use_cases.fraud_review.upload_fraud_label_review_import import (
    UploadFraudLabelReviewImport,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
)
from src.infrastructure.entrypoint.api.factories.metrics_factory import (
    get_record_alert_metrics_event_use_case,
)
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_label_review_repository import (
    DynamoFraudLabelReviewRepository,
)


@lru_cache
def get_fraud_label_review_repository() -> DynamoFraudLabelReviewRepository:
    return DynamoFraudLabelReviewRepository()


@lru_cache
def get_fraud_label_review_import_dispatcher() -> FraudLabelReviewImportDispatcher:
    # Lazy import - keeps celery out of the API process's import graph.
    from src.infrastructure.queues.celery.fraud_label_review_import_dispatcher import (
        CeleryFraudLabelReviewImportDispatcher,
    )

    return CeleryFraudLabelReviewImportDispatcher()


@lru_cache
def get_fraud_label_review_import_status_reader() -> FraudLabelReviewImportStatusReader:
    from src.infrastructure.queues.celery.fraud_label_review_import_status_reader import (
        CeleryFraudLabelReviewImportStatusReader,
    )

    return CeleryFraudLabelReviewImportStatusReader()


def get_list_alert_history_use_case() -> ListAlertHistory:
    return ListAlertHistory(
        alert_repository=get_alert_repository(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
    )


def get_review_fraud_label_use_case() -> ReviewFraudLabel:
    return ReviewFraudLabel(
        alert_repository=get_alert_repository(),
        review_repository=get_fraud_label_review_repository(),
        record_metrics_event=get_record_alert_metrics_event_use_case(),
        monitoring=get_monitoring(),
    )


def get_list_fraud_label_reviews_use_case() -> ListFraudLabelReviews:
    return ListFraudLabelReviews(review_repository=get_fraud_label_review_repository())


def get_upload_fraud_label_review_import_use_case() -> UploadFraudLabelReviewImport:
    return UploadFraudLabelReviewImport(dispatcher=get_fraud_label_review_import_dispatcher())


def get_get_fraud_label_review_import_use_case() -> GetFraudLabelReviewImport:
    return GetFraudLabelReviewImport(reader=get_fraud_label_review_import_status_reader())
