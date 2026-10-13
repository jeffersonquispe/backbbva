from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from src.domain.configurations.entities import (
    ConfigurationRef,
)


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
    # How many times classification+adversarial can loop back before
    # escalating to an analyst - see WorkflowExecutionRecord.
    # max_feedback_iterations (workflow_port.py) and
    # AlertReviewWorkflowRunner._run_adversarial_review. Kept low by
    # default - each loop-back re-runs classification+adversarial (real
    # LLM calls), and Celery's autoretry on the outer task compounds this
    # further on final escalation, so raising it has real token/cost
    # impact.
    max_feedback_iterations: int = 1
    # Which stored ConfigurationRecord to resolve segments against for this
    # test run - None (default) keeps today's behavior, resolving against
    # ConfigurationRepository.get_active(). Set to test against a specific
    # (possibly inactive) config without touching the global active flag,
    # so multiple test runs can each target a different configuration
    # concurrently - see alert_review_workflow.py's _resolve_segment.
    configuration_ref: ConfigurationRef | None = None
    schema_version: int | None = None


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
