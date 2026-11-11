"""Cold fraud-history archive reads and legal holds (#11c) wiring for the API."""

from __future__ import annotations

from functools import lru_cache

from src.application.ports.fraud_history_archive_index_port import (
    ArchiveIndexPort,
)
from src.application.ports.fraud_history_archive_reader_port import (
    FraudHistoryArchiveReaderPort,
)
from src.application.ports.legal_hold_port import LegalHoldRepository
from src.application.use_cases.fraud_review.get_archived_alert import GetArchivedAlert
from src.application.use_cases.fraud_review.manage_legal_hold import (
    GetLegalHold,
    ListLegalHolds,
    PlaceLegalHold,
    ReleaseLegalHold,
)
from src.application.use_cases.fraud_review.search_archived_alerts import (
    SearchArchivedAlerts,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
)
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_index_repository import (
    DynamoFraudHistoryArchiveIndex,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_reader import (
    DynamoFraudHistoryArchiveReader,
)
from src.infrastructure.persistence.database.dynamodb.repositories.legal_hold_repository import (
    DynamoLegalHoldRepository,
)
from src.infrastructure.persistence.object_storage.minio import get_object_storage


@lru_cache(maxsize=1)
def get_fraud_history_archive_index() -> ArchiveIndexPort:
    return DynamoFraudHistoryArchiveIndex()


@lru_cache(maxsize=1)
def get_legal_hold_repository() -> LegalHoldRepository:
    return DynamoLegalHoldRepository()


@lru_cache(maxsize=1)
def get_fraud_history_archive_reader() -> FraudHistoryArchiveReaderPort:
    return DynamoFraudHistoryArchiveReader(
        get_object_storage(), get_fraud_history_archive_index()
    )


def get_get_archived_alert_use_case() -> GetArchivedAlert:
    return GetArchivedAlert(
        get_fraud_history_archive_reader(), get_audit_repository(), get_clock()
    )


def get_place_legal_hold_use_case() -> PlaceLegalHold:
    return PlaceLegalHold(
        holds=get_legal_hold_repository(),
        alerts=get_alert_repository(),
        archive=get_fraud_history_archive_reader(),
        clock=get_clock(),
        audit=get_audit_repository(),
    )


def get_release_legal_hold_use_case() -> ReleaseLegalHold:
    return ReleaseLegalHold(
        get_legal_hold_repository(), get_clock(), get_audit_repository()
    )


def get_list_legal_holds_use_case() -> ListLegalHolds:
    return ListLegalHolds(get_legal_hold_repository())


def get_search_archived_alerts_use_case() -> SearchArchivedAlerts:
    return SearchArchivedAlerts(
        get_fraud_history_archive_reader(),
        get_legal_hold_repository(),
        get_audit_repository(),
        get_clock(),
    )


def get_get_legal_hold_use_case() -> GetLegalHold:
    return GetLegalHold(get_legal_hold_repository())
