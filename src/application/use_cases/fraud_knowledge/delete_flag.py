from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FlagDocument,
    ModusOperandiDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)


class DeleteFlagUseCase:
    """Removes the id from every parent modus_operandi's flags list (M2M)
    before deleting the document itself."""

    def __init__(self, repository: FraudKnowledgeRepository) -> None:
        self._repository = repository

    def execute(self, flag_id: UUID) -> None:
        document = self._repository.get(flag_id)
        if document is None or document.type not in (
            DocumentType.RED_FLAG,
            DocumentType.YELLOW_FLAG,
        ):
            raise ValueError(f"flag {flag_id} not found")
        assert isinstance(document, FlagDocument)

        for modus_operandi_id in document.modus_operandi_ids:
            parent = self._repository.get(modus_operandi_id)
            if parent is not None and parent.type == DocumentType.MODUS_OPERANDI:
                assert isinstance(parent, ModusOperandiDocument)
                self._repository.update(
                    replace(
                        parent,
                        flags=[fid for fid in parent.flags if fid != flag_id],
                    )
                )

        self._repository.delete(flag_id)
