from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass
class FeedbackRecord:
    """An analyst's structured feedback about a specific configuration
    version, captured from the "Al dataset" alert-curation action. Owned by
    the configuration it's about (configuration_id + version), not by the
    dataset the alert also got curated into - dataset_name is kept only as
    a cross-reference for traceability, never the primary association."""

    id: UUID
    configuration_id: str
    version: int
    alert_id: UUID
    justification: str
    dataset_name: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None


class FeedbackRepository(Protocol):
    def create(self, feedback: FeedbackRecord) -> FeedbackRecord: ...

    def get(self, feedback_id: UUID) -> FeedbackRecord | None: ...

    def list(
        self,
        configuration_id: str | None = None,
        version: int | None = None,
    ) -> list[FeedbackRecord]: ...
