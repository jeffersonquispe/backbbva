from __future__ import annotations

from src.application.errors import NotFoundError
from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.flag_library_port import (
    FlagLibraryRepository,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.flag_library.create_flag_library_entry import (
    embedding_text,
)
from src.domain.configurations.entities import (
    FlagType,
)
from src.domain.fraud_knowledge.library_entities import FlagLibraryEntry


class FlagLibraryEntryNotFoundError(NotFoundError):
    pass


class UpdateFlagLibraryEntryUseCase:
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
        entry_id: str,
        *,
        flag_type: FlagType | None = None,
        name: str | None = None,
        description: str | None = None,
        evolved_variables: list[str] | None = None,
        modus_operandi_library_ids: list[str] | None = None,
        active: bool | None = None,
    ) -> FlagLibraryEntry:
        current = self._entries.get(entry_id)
        if current is None:
            raise FlagLibraryEntryNotFoundError(
                f"Flag library entry not found: {entry_id}"
            )

        embedding: list[float] | None = None
        text_changed = (name is not None and name != current.name) or (
            description is not None and description != current.description
        )
        if text_changed:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="embed_flag_library_entry",
            )
            embedding = uow.embed(
                [
                    embedding_text(
                        name=name if name is not None else current.name,
                        description=description
                        if description is not None
                        else current.description,
                    )
                ]
            ).vectors[0]

        updated = self._entries.update(
            entry_id,
            flag_type=flag_type,
            name=name,
            description=description,
            evolved_variables=evolved_variables,
            modus_operandi_library_ids=modus_operandi_library_ids,
            active=active,
            embedding=embedding,
        )
        if updated is None:
            raise FlagLibraryEntryNotFoundError(
                f"Flag library entry not found: {entry_id}"
            )
        return updated
