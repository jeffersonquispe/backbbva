from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.domain.fraud_knowledge.library_entities import ModusOperandiPlaybook


@dataclass(frozen=True)
class ModusOperandiDraftFields:
    title: str
    narrative: str
    taxonomy_library_id: str
    evolved_variables: list[str]
    playbook: ModusOperandiPlaybook


class ModusOperandiDraftApplier(Protocol):
    def create(self, fields: ModusOperandiDraftFields) -> str: ...

    def update(
        self,
        entry_id: str,
        fields: ModusOperandiDraftFields,
        expected_updated_at: datetime,
    ) -> str: ...
