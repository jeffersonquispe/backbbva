from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.flag_library_port import (
    FlagLibraryRepository,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import MonitoringPort
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.configurations.entities import (
    FlagType,
)
from src.domain.fraud_knowledge.library_entities import FlagLibraryEntry


def embedding_text(*, name: str, description: str) -> str:
    return f"{name}: {description}"


class CreateFlagLibraryEntryUseCase:
    def __init__(
        self,
        flag_library_repository: FlagLibraryRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._entries = flag_library_repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self,
        flag_type: FlagType,
        name: str,
        description: str = "",
        evolved_variables: list[str] | None = None,
        modus_operandi_library_ids: list[str] | None = None,
    ) -> FlagLibraryEntry:
        normalized_name = " ".join(name.split()).casefold()
        for existing in self._entries.list():
            if (
                " ".join(existing.name.split()).casefold() == normalized_name
                and existing.flag_type == flag_type
            ):
                return existing
        now = self._clock.now()
        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="embed_flag_library_entry",
        )
        embedding = uow.embed(
            [embedding_text(name=name, description=description)]
        ).vectors[0]
        return self._entries.create(
            FlagLibraryEntry(
                id=str(self._id_generator.new_id()),
                flag_type=flag_type,
                name=name,
                description=description,
                evolved_variables=evolved_variables or [],
                modus_operandi_library_ids=modus_operandi_library_ids or [],
                created_at=now,
                updated_at=now,
                embedding=embedding,
            )
        )
