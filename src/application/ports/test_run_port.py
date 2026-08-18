from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class TestRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass
class TestRunConfig:
    # step_name -> override, e.g. {"classification": "..."}. Empty means
    # "use the config-driven default for every step" - the lean bundle
    # described in CLAUDE.md, not a versioned/persisted config entity.
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    model_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class TestRunRecord:
    id: UUID
    name: str
    dataset_name: str
    config: TestRunConfig
    status: TestRunStatus
    total: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class TestRunRepository(Protocol):
    def create(self, run: TestRunRecord) -> TestRunRecord:
        ...

    def get(self, run_id: UUID) -> TestRunRecord | None:
        ...

    def update(
        self,
        run_id: UUID,
        *,
        status: TestRunStatus | None = None,
        finished_at: datetime | None = None,
    ) -> TestRunRecord | None:
        ...

    def list(self) -> list[TestRunRecord]:
        ...
