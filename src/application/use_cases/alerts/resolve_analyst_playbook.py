from __future__ import annotations

from src.application.ports.configuration_port import AnalystPlaybook
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
    SearchPipeline,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
    VectorStoreNotPromotedError,
)

# How many of the closest modus-operandi matches to check for a configured
# playbook before giving up - a segment's Library can have modus operandi
# entries with no playbook attached yet, so the single closest match isn't
# necessarily the one an admin has written a playbook for.
_TOP_K = 5


class ResolveAnalystPlaybookUseCase:
    """Finds which of a segment's AnalystPlaybook entries (if any) matches
    the alert's likely modus operandi.

    Searches the same vector_store_instance_id Detector/Clasificación
    already select (confirmed to be the same instance - see
    configuration_port.py's ClassificationConfig.vector_store_instance_id),
    scoped to MODUS_OPERANDI documents, and joins the ranked hits against
    each playbook's `modus_operandi_id` via ModusOperandiDocument.library_id
    (the document's own id is a fresh uuid4 per promotion, not a stable
    reference an admin could pick in the UI - see that field's docstring).

    Advisory only: the caller (AnalystReviewAlertUseCase) feeds a resolved
    playbook to the analyst LLM as extra context, it does not short-circuit
    the decision - that was an explicit product choice, not an oversight.
    """

    def __init__(self, search_use_case: SearchFraudKnowledgeUseCase) -> None:
        self._search_use_case = search_use_case

    def execute(
        self,
        query: str,
        *,
        vector_store_instance_id: str | None,
        playbooks: list[AnalystPlaybook],
    ) -> AnalystPlaybook | None:
        by_modus_operandi_id = {
            playbook.modus_operandi_id: playbook
            for playbook in playbooks
            if playbook.modus_operandi_id
        }
        if not by_modus_operandi_id or not vector_store_instance_id:
            return None
        try:
            results = self._search_use_case.execute(
                query,
                pipeline=SearchPipeline.BALANCED,
                vector_store_id=vector_store_instance_id,
                document_type=DocumentType.MODUS_OPERANDI,
                top_k=_TOP_K,
            )
        except VectorStoreNotPromotedError:
            return None
        for result in results:
            document = result.document
            assert isinstance(document, ModusOperandiDocument)
            playbook = by_modus_operandi_id.get(document.library_id)
            if playbook is not None:
                return playbook
        return None
