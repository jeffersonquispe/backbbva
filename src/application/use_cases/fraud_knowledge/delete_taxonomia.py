from __future__ import annotations

from uuid import UUID

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
    TaxonomiaDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.use_cases.fraud_knowledge.delete_modus_operandi import (
    DeleteModusOperandiUseCase,
)


class DeleteTaxonomiaUseCase:
    """Cascades through every child modus_operandi (and, transitively,
    their similar_case/red_flag/yellow_flag children) before deleting the
    taxonomia itself."""

    def __init__(self, repository: FraudKnowledgeRepository) -> None:
        self._repository = repository
        self._delete_modus_operandi = DeleteModusOperandiUseCase(repository)

    def execute(self, taxonomia_id: UUID) -> None:
        document = self._repository.get(taxonomia_id)
        if not isinstance(document, TaxonomiaDocument):
            raise ValueError(f"taxonomia {taxonomia_id} not found")

        # ponytail: O(n) scan over all modus_operandi to find children —
        # fine at reference/config-data scale, add a list-by-parent-id
        # repository method if fraud-knowledge volume ever gets large.
        children = [
            doc
            for doc in self._repository.list(DocumentType.MODUS_OPERANDI)
            if isinstance(doc, ModusOperandiDocument)
            and doc.taxonomia_id == taxonomia_id
        ]
        for child in children:
            self._delete_modus_operandi.execute(child.id)

        self._repository.delete(taxonomia_id)
