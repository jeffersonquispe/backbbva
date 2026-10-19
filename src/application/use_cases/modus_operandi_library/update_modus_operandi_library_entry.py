from __future__ import annotations

from src.application.errors import NotFoundError, ValidationError
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
from src.domain.fraud_knowledge.library_entities import (
    FALLBACK_RESOLUTION_TAGS,
    PRIMARY_RESOLUTION_TAGS,
    ModusOperandiLibraryEntry,
    ModusOperandiPlaybook,
)


class ModusOperandiLibraryEntryNotFoundError(NotFoundError):
    pass


class InvalidModusOperandiPlaybookError(ValidationError):
    pass


def validate_playbook(playbook: ModusOperandiPlaybook) -> None:
    if playbook.resolution.resolution_tag not in PRIMARY_RESOLUTION_TAGS:
        raise InvalidModusOperandiPlaybookError(
            "Playbook resolution must be scale_to_analyst, send_to_voicebot "
            "or handle_by_aria."
        )
    for name, fallback in (
        ("if_no_voicebot", playbook.if_no_voicebot),
        ("if_no_analyst", playbook.if_no_analyst),
    ):
        if fallback.resolution_tag not in FALLBACK_RESOLUTION_TAGS:
            raise InvalidModusOperandiPlaybookError(
                f"Playbook {name} must name a resource or a block, "
                "not handle_by_aria."
            )
    # A resource can't be its own fallback (voicebot short -> voicebot).
    if playbook.if_no_voicebot.resolution_tag == "send_to_voicebot":
        raise InvalidModusOperandiPlaybookError(
            "if_no_voicebot cannot route back to the voicebot."
        )
    if playbook.if_no_analyst.resolution_tag == "scale_to_analyst":
        raise InvalidModusOperandiPlaybookError(
            "if_no_analyst cannot route back to an analyst."
        )


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
        )
        if updated is None:
            raise ModusOperandiLibraryEntryNotFoundError(
                f"Modus operandi library entry not found: {entry_id}"
            )
        return updated
