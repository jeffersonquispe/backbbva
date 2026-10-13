from __future__ import annotations

from src.application.ports.e2e_state_cleaner_port import (
    E2EStateCleaner,
    E2EStateCleanResult,
)
from src.application.use_cases.e2e.clean_e2e_state import CleanE2EStateUseCase


class RecordingE2EStateCleaner(E2EStateCleaner):
    def __init__(self) -> None:
        self.calls = 0

    def clean(self) -> E2EStateCleanResult:
        self.calls += 1
        return E2EStateCleanResult(
            deleted_items=7, preserved_tables=["users"], table_count=3
        )


def test_clean_delegates_to_the_cleaner_and_returns_its_result() -> None:
    cleaner = RecordingE2EStateCleaner()

    result = CleanE2EStateUseCase(cleaner).execute()

    assert cleaner.calls == 1
    assert result.deleted_items == 7
    assert result.preserved_tables == ["users"]
    assert result.table_count == 3
