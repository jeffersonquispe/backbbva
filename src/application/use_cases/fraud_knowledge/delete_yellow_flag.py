from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)


class DeleteYellowFlagUseCase:
    """Removes the id from the parent modus_operandi's yellow_flags list
    before deleting the document itself."""

    def __init__(self, repository: FraudKnowledgeRepository) -> None:
        self._repository = repository

    def execute(self, yellow_flag_id: UUID) -> None:
        document = self._repository.get(yellow_flag_id)
        if document is None or document.type != DocumentType.YELLOW_FLAG:
            raise ValueError(f"yellow_flag {yellow_flag_id} not found")

        parent = self._repository.get(document.modus_operandi_id)
        if parent is not None and parent.type == DocumentType.MODUS_OPERANDI:
            assert isinstance(parent, ModusOperandiDocument)
            self._repository.update(
                replace(
                    parent,
                    yellow_flags=[
                        fid for fid in parent.yellow_flags if fid != yellow_flag_id
                    ],
                )
            )

        self._repository.delete(yellow_flag_id)
