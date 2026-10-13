from __future__ import annotations

from functools import lru_cache

from src.application.ports.e2e_state_cleaner_port import E2EStateCleaner
from src.application.use_cases.e2e.clean_e2e_state import CleanE2EStateUseCase
from src.infrastructure.persistence.database.dynamodb.repositories.e2e_state_cleaner import (
    DynamoE2EStateCleaner,
)


@lru_cache
def get_e2e_state_cleaner() -> E2EStateCleaner:
    return DynamoE2EStateCleaner()


def get_clean_e2e_state_use_case() -> CleanE2EStateUseCase:
    return CleanE2EStateUseCase(get_e2e_state_cleaner())
