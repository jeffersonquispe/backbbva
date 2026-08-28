from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from src.application.ports.fraud_knowledge_port import DocumentType, FlagDocument
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)


class DeleteModusOperandiUseCase:
    """Cascades: deletes every exclusively-owned similar_case, and for
    each flag (M2M) either detaches this modus_operandi from it (if the
    flag has other parents left) or deletes it (if this was its last
    parent) - then deletes the modus_operandi itself."""

    def __init__(self, repository: FraudKnowledgeRepository) -> None:
        self._repository = repository

    def execute(self, modus_operandi_id: UUID) -> None:
        document = self._repository.get(modus_operandi_id)
        if document is None or document.type != DocumentType.MODUS_OPERANDI:
            raise ValueError(f"modus_operandi {modus_operandi_id} not found")

        for similar_case_id in document.similar_cases:
            self._repository.delete(similar_case_id)

        for flag_id in document.flags:
            flag = self._repository.get(flag_id)
            if flag is None:
                continue
            assert isinstance(flag, FlagDocument)
            remaining = [
                mid for mid in flag.modus_operandi_ids if mid != modus_operandi_id
            ]
            if remaining:
                self._repository.update(replace(flag, modus_operandi_ids=remaining))
            else:
                self._repository.delete(flag_id)

        self._repository.delete(modus_operandi_id)
