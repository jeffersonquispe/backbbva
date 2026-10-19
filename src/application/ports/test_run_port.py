from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.domain.test_runs.entities import (
    TestRunConfig,
    TestRunRecord,
    TestRunStatus,
)

__all__ = ["TestRunConfig", "TestRunRecord", "TestRunRepository", "TestRunStatus"]


class TestRunRepository(Protocol):
    def create(self, run: TestRunRecord) -> TestRunRecord: ...

    def get(self, run_id: UUID) -> TestRunRecord | None: ...

    def update(
        self,
        run_id: UUID,
        *,
        status: TestRunStatus | None = None,
        finished_at: datetime | None = None,
    ) -> TestRunRecord | None: ...

    def list(self) -> list[TestRunRecord]: ...

    def delete(self, run_id: UUID) -> None: ...
