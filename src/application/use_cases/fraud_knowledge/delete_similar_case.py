from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
    SimilarCaseDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)


class DeleteSimilarCaseUseCase:
    """Removes the id from the parent modus_operandi's similar_cases list
    before deleting the document itself."""

    def __init__(self, repository: FraudKnowledgeRepository) -> None:
        self._repository = repository

    def execute(self, similar_case_id: UUID) -> None:
        document = self._repository.get(similar_case_id)
        if not isinstance(document, SimilarCaseDocument):
            raise ValueError(f"similar_case {similar_case_id} not found")

        parent = self._repository.get(document.modus_operandi_id)
        if parent is not None and parent.type == DocumentType.MODUS_OPERANDI:
            assert isinstance(parent, ModusOperandiDocument)
            self._repository.update(
                replace(
                    parent,
                    similar_cases=[
                        cid for cid in parent.similar_cases if cid != similar_case_id
                    ],
                )
            )

        self._repository.delete(similar_case_id)
