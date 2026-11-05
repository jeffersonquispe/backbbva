from __future__ import annotations

from datetime import date
from functools import lru_cache

from src.application.ports.e2e_state_cleaner_port import E2EStateCleaner
from src.application.use_cases.e2e.clean_e2e_state import CleanE2EStateUseCase
from src.infrastructure.persistence.database.dynamodb.repositories.e2e_state_cleaner import (
    DynamoE2EStateCleaner,
)
from src.infrastructure.persistence.object_storage.minio import get_object_storage


@lru_cache
def get_e2e_state_cleaner() -> E2EStateCleaner:
    return DynamoE2EStateCleaner()


def get_clean_e2e_state_use_case() -> CleanE2EStateUseCase:
    return CleanE2EStateUseCase(get_e2e_state_cleaner())


def get_e2e_object_storage():
    return get_object_storage()


E2E_ARCHIVED_ALERT_ID = "00000000-0000-4000-8000-0000000011c0"
E2E_ARCHIVED_EVENT_ID = "E2E-11C-ARCHIVED"
E2E_ARCHIVED_DAY = date(2024, 2, 29)


class SeedArchivedAlert:
    """Local E2E only: put one backdated alert in the real alerts table and move
    it to the cold archive with the real archiver (object, index, delete), so the
    archive lookup can be exercised against data that is genuinely archived.
    Idempotent: the object name is the SHA-256 of its fixed content."""

    def execute(self) -> dict[str, str]:
        from src.infrastructure.entrypoint.api.factories.fraud_archive_factory import (
            get_fraud_history_archive_index,
            get_legal_hold_repository,
        )
        from src.infrastructure.persistence.database.dynamodb.client import (
            get_dynamodb_resource,
        )
        from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_repository import (
            ALERTS_TABLE_NAME,
            DynamoFraudHistoryArchiveRepository,
        )

        day = E2E_ARCHIVED_DAY.isoformat()
        get_dynamodb_resource().Table(ALERTS_TABLE_NAME).put_item(
            Item={
                "partition": "alert",
                "alert_id": E2E_ARCHIVED_ALERT_ID,
                "event_id": E2E_ARCHIVED_EVENT_ID,
                "event_type": "E2E archived alert",
                "created_day": day,
                "created_at": f"{day}T15:00:00+00:00",
                "updated_at": f"{day}T15:00:00+00:00",
                "status": "CLOSED",
                "input": {"channel": "E2E", "note": "alerta archivada sintética"},
            }
        )
        archived = DynamoFraudHistoryArchiveRepository(
            get_object_storage(),
            index=get_fraud_history_archive_index(),
            holds=get_legal_hold_repository(),
        ).archive_day(E2E_ARCHIVED_DAY, dry_run=False)
        return {
            "alert_id": E2E_ARCHIVED_ALERT_ID,
            "event_id": E2E_ARCHIVED_EVENT_ID,
            "created_day": day,
            "archive_object": archived.object_key or "",
        }


def get_seed_archived_alert() -> SeedArchivedAlert:
    return SeedArchivedAlert()
