from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryEntry,
    ModusOperandiLibraryRepository,
)
from src.application.ports.monitoring_port import MonitoringPort


def embedding_text(*, title: str, narrative: str) -> str:
    return f"{title}: {narrative}"


class CreateModusOperandiLibraryEntryUseCase:
    def __init__(
        self,
        modus_operandi_library_repository: ModusOperandiLibraryRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
    ) -> None:
        self._entries = modus_operandi_library_repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model

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
        now = datetime.now(timezone.utc)
        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="embed_modus_operandi_library_entry",
        )
        embedding = uow.embed([embedding_text(title=title, narrative=narrative)]).vectors[0]
        return self._entries.create(
            ModusOperandiLibraryEntry(
                id=str(uuid.uuid4()),
                title=title,
                narrative=narrative,
                taxonomy_library_id=taxonomy_library_id,
                evolved_variables=evolved_variables or [],
                created_at=now,
                updated_at=now,
                embedding=embedding,
            )
        )
