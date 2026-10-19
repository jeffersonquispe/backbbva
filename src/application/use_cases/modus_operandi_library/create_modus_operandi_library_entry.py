from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.fraud_knowledge.library_entities import ModusOperandiLibraryEntry


def embedding_text(*, title: str, narrative: str) -> str:
    return f"{title}: {narrative}"


class CreateModusOperandiLibraryEntryUseCase:
    def __init__(
        self,
        modus_operandi_library_repository: ModusOperandiLibraryRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._entries = modus_operandi_library_repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self,
        title: str,
        narrative: str,
        taxonomy_library_id: str,
        evolved_variables: list[str] | None = None,
    ) -> ModusOperandiLibraryEntry:
        normalized_title = " ".join(title.split()).casefold()
        for existing in self._entries.list():
            if " ".join(existing.title.split()).casefold() == normalized_title:
                return existing
        now = self._clock.now()
        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="embed_modus_operandi_library_entry",
        )
        embedding = uow.embed(
            [embedding_text(title=title, narrative=narrative)]
        ).vectors[0]
        return self._entries.create(
            ModusOperandiLibraryEntry(
                id=str(self._id_generator.new_id()),
                title=title,
                narrative=narrative,
                taxonomy_library_id=taxonomy_library_id,
                evolved_variables=evolved_variables or [],
                created_at=now,
                updated_at=now,
                embedding=embedding,
            )
        )
