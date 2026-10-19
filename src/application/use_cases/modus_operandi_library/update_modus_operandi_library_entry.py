from __future__ import annotations

from datetime import datetime

from src.application.errors import NotFoundError
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.modus_operandi_library.create_modus_operandi_library_entry import (
    embedding_text,
)
from src.application.use_cases.modus_operandi_library.playbook_validation import (
    InvalidModusOperandiPlaybookError,
    validate_playbook,
)
from src.domain.fraud_knowledge.library_entities import (
    ModusOperandiLibraryEntry,
    ModusOperandiPlaybook,
)

__all__ = [
    "InvalidModusOperandiPlaybookError",
    "ModusOperandiLibraryEntryNotFoundError",
    "UpdateModusOperandiLibraryEntryUseCase",
]


class ModusOperandiLibraryEntryNotFoundError(NotFoundError):
    pass


class UpdateModusOperandiLibraryEntryUseCase:
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
        entry_id: str,
        *,
        title: str | None = None,
        narrative: str | None = None,
        taxonomy_library_id: str | None = None,
        evolved_variables: list[str] | None = None,
        active: bool | None = None,
        playbook: ModusOperandiPlaybook | None = None,
        expected_updated_at: datetime | None = None,
    ) -> ModusOperandiLibraryEntry:
        if playbook is not None:
            validate_playbook(playbook)
        current = self._entries.get(entry_id)
        if current is None:
            raise ModusOperandiLibraryEntryNotFoundError(
                f"Modus operandi library entry not found: {entry_id}"
            )

        embedding: list[float] | None = None
        text_changed = (title is not None and title != current.title) or (
            narrative is not None and narrative != current.narrative
        )
        if text_changed:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="embed_modus_operandi_library_entry",
            )
            embedding = uow.embed(
                [
                    embedding_text(
                        title=title if title is not None else current.title,
                        narrative=narrative
                        if narrative is not None
                        else current.narrative,
                    )
                ]
            ).vectors[0]

        updated = self._entries.update(
            entry_id,
            title=title,
            narrative=narrative,
            taxonomy_library_id=taxonomy_library_id,
            evolved_variables=evolved_variables,
            active=active,
            embedding=embedding,
            playbook=playbook,
            expected_updated_at=expected_updated_at,
        )
        if updated is None:
            raise ModusOperandiLibraryEntryNotFoundError(
                f"Modus operandi library entry not found: {entry_id}"
            )
        return updated
