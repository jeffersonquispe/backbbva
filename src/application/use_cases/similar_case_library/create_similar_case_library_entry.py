from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryEntry,
    SimilarCaseLibraryRepository,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class CreateSimilarCaseLibraryEntryUseCase:
    def __init__(
        self,
        similar_case_library_repository: SimilarCaseLibraryRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._entries = similar_case_library_repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self, text: str, modus_operandi_library_id: str, taxonomy_library_id: str
    ) -> SimilarCaseLibraryEntry:
        normalized_text = " ".join(text.split()).casefold()
        for existing in self._entries.list():
            if (
                " ".join(existing.text.split()).casefold() == normalized_text
                and existing.modus_operandi_library_id == modus_operandi_library_id
            ):
                return existing
        now = self._clock.now()
        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="embed_similar_case_library_entry",
        )
        embedding = uow.embed([text]).vectors[0]
        return self._entries.create(
            SimilarCaseLibraryEntry(
                id=str(self._id_generator.new_id()),
                text=text,
                modus_operandi_library_id=modus_operandi_library_id,
                taxonomy_library_id=taxonomy_library_id,
                created_at=now,
                updated_at=now,
                embedding=embedding,
            )
        )
