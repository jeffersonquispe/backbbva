from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.configuration_port import FlagType
from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.flag_library_port import FlagLibraryEntry, FlagLibraryRepository
from src.application.ports.monitoring_port import MonitoringPort


def embedding_text(*, name: str, description: str) -> str:
    return f"{name}: {description}"


class CreateFlagLibraryEntryUseCase:
    def __init__(
        self,
        flag_library_repository: FlagLibraryRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
    ) -> None:
        self._entries = flag_library_repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model

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
            if " ".join(existing.name.split()).casefold() == normalized_name and existing.flag_type == flag_type:
                return existing
        now = datetime.now(timezone.utc)
        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="embed_flag_library_entry",
        )
        embedding = uow.embed([embedding_text(name=name, description=description)]).vectors[0]
        return self._entries.create(
            FlagLibraryEntry(
                id=str(uuid.uuid4()),
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
