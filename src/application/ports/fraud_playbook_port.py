from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class FraudPlaybookRecord:
    classification: str
    title: str
    steps: list[str]
    created_at: datetime
    updated_at: datetime


class FraudPlaybookRepository(Protocol):
    def create(self, playbook: FraudPlaybookRecord) -> FraudPlaybookRecord:
        ...

    def get(self, classification: str) -> FraudPlaybookRecord | None:
        ...

    def update(
        self,
        classification: str,
        *,
        title: str | None = None,
        steps: list[str] | None = None,
    ) -> FraudPlaybookRecord | None:
        ...

    def list(self) -> list[FraudPlaybookRecord]:
        ...
