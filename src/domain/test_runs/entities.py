from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.domain.configurations.entities import ConfigurationRef


class TestRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass
class TestRunConfig:
    """Options captured when a test run starts and passed to its alert jobs."""

    # Per-step overrides; empty dictionaries select the active configuration.
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    model_overrides: dict[str, str] = field(default_factory=dict)
    # Maximum classification/adversarial feedback loop-backs per alert.
    max_feedback_iterations: int = 1
    # Optional pinned configuration and schema versions for reproducibility.
    configuration_ref: ConfigurationRef | None = None
    schema_version: int | None = None
    active_schema_version: int | None = None


@dataclass
class TestRunRecord:
    """Persistent identity, configuration, and lifecycle state of a test run."""

    id: UUID
    name: str
    dataset_name: str
    config: TestRunConfig
    status: TestRunStatus
    total: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
