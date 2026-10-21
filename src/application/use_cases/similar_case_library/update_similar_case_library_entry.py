from __future__ import annotations

from datetime import datetime

from src.application.errors import NotFoundError
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryRepository,
)
from src.domain.fraud_knowledge.library_entities import SimilarCaseLibraryEntry


class SimilarCaseLibraryEntryNotFoundError(NotFoundError):
    pass


class UpdateSimilarCaseLibraryEntryUseCase:
    def __init__(
        self,
        similar_case_library_repository: SimilarCaseLibraryRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
    ) -> None:
        self._entries = similar_case_library_repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model

    def execute(
        self,
        entry_id: str,
        *,
        text: str | None = None,
        modus_operandi_library_id: str | None = None,
        taxonomy_library_id: str | None = None,
        active: bool | None = None,
        expected_updated_at: datetime | None = None,
    ) -> SimilarCaseLibraryEntry:
        current = self._entries.get(entry_id)
        if current is None:
            raise SimilarCaseLibraryEntryNotFoundError(
                f"Similar case library entry not found: {entry_id}"
            )

        embedding: list[float] | None = None
        if text is not None and text != current.text:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="embed_similar_case_library_entry",
            )
            embedding = uow.embed([text]).vectors[0]

        updated = self._entries.update(
            entry_id,
            text=text,
            modus_operandi_library_id=modus_operandi_library_id,
            taxonomy_library_id=taxonomy_library_id,
            active=active,
            embedding=embedding,
            expected_updated_at=expected_updated_at,
        )
        if updated is None:
            raise SimilarCaseLibraryEntryNotFoundError(
                f"Similar case library entry not found: {entry_id}"
            )
        return updated
