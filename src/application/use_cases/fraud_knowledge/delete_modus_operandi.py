from __future__ import annotations

from uuid import UUID

from src.application.ports.fraud_knowledge_port import DocumentType
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)


class DeleteModusOperandiUseCase:
    """Cascades: deletes every similar_case/red_flag/yellow_flag listed on
    the modus_operandi, then the modus_operandi itself."""

    def __init__(self, repository: FraudKnowledgeRepository) -> None:
        self._repository = repository

    def execute(self, modus_operandi_id: UUID) -> None:
        document = self._repository.get(modus_operandi_id)
        if document is None or document.type != DocumentType.MODUS_OPERANDI:
            raise ValueError(f"modus_operandi {modus_operandi_id} not found")

        for child_id in (
            *document.similar_cases,
            *document.red_flags,
            *document.yellow_flags,
        ):
            self._repository.delete(child_id)

        self._repository.delete(modus_operandi_id)
