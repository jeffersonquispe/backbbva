from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
    SearchPipeline,
)
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
    VectorStoreNotPromotedError,
)
from src.domain.fraud_knowledge.library_entities import ModusOperandiPlaybook

# How many of the closest modus-operandi matches to check for a written
# playbook before giving up - the Library can have modus operandi entries
# with no playbook yet, so the single closest match isn't necessarily one
# an admin has written a playbook for.
_TOP_K = 5


@dataclass(frozen=True)
class ResolvedPlaybook:
    modus_operandi_id: str
    modus_operandi_title: str
    playbook: ModusOperandiPlaybook


class ResolveAnalystPlaybookUseCase:
    """Finds the playbook for the modus operandi the alert most resembles.

    Searches the segment's vector store (the same instance Detector/
    Clasificación use), scoped to MODUS_OPERANDI documents, and joins each
    ranked hit back to its live Library entry via
    ModusOperandiDocument.library_id (the document's own id is a fresh
    uuid4 per promotion). The playbook is read from the Library entry - not
    from the promoted snapshot - so edits take effect without re-promoting.

    Returns None when no vector store is selected, it was never promoted,
    or none of the closest matches has a playbook: the caller then applies
    the no-playbook default (escalate to an analyst, block soft if none).
    """

    def __init__(
        self,
        search_use_case: SearchFraudKnowledgeUseCase,
        modus_operandi_library: ModusOperandiLibraryRepository,
    ) -> None:
        self._search_use_case = search_use_case
        self._library = modus_operandi_library

    def execute(
        self,
        query: str,
        *,
        vector_store_instance_id: str | None,
        library_revision_pin: dict[str, str] | None = None,
    ) -> ResolvedPlaybook | None:
        if not vector_store_instance_id:
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
            if not document.library_id:
                continue
            if library_revision_pin is not None:
                if document.library_id != library_revision_pin.get("entity_id"):
                    continue
                revision = self._library.get_revision(
                    document.library_id, library_revision_pin.get("version", "")
                )
                entry = revision.content if revision is not None else None
            else:
                entry = self._library.get(document.library_id)
            if entry is None or not entry.active or entry.playbook is None:
                continue
            return ResolvedPlaybook(
                modus_operandi_id=entry.id,
                modus_operandi_title=entry.title,
                playbook=entry.playbook,
            )
        return None
