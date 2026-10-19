from __future__ import annotations

from datetime import datetime

from src.application.ports.agent_modus_operandi_draft_applier_port import (
    ModusOperandiDraftApplier,
    ModusOperandiDraftFields,
)
from src.application.use_cases.modus_operandi_library.create_modus_operandi_library_entry import (
    CreateModusOperandiLibraryEntryUseCase,
)
from src.application.use_cases.modus_operandi_library.update_modus_operandi_library_entry import (
    UpdateModusOperandiLibraryEntryUseCase,
)


class ExistingModusOperandiUseCasesApplier(ModusOperandiDraftApplier):
    def __init__(
        self,
        *,
        create: CreateModusOperandiLibraryEntryUseCase,
        update: UpdateModusOperandiLibraryEntryUseCase,
    ) -> None:
        self._create = create
        self._update = update

    def create(self, fields: ModusOperandiDraftFields) -> str:
        entry = self._create.execute(
            fields.title,
            fields.narrative,
            fields.taxonomy_library_id,
            fields.evolved_variables,
            fields.playbook,
        )
        return entry.id

    def update(
        self,
        entry_id: str,
        fields: ModusOperandiDraftFields,
        expected_updated_at: datetime,
    ) -> str:
        entry = self._update.execute(
            entry_id,
            title=fields.title,
            narrative=fields.narrative,
            taxonomy_library_id=fields.taxonomy_library_id,
            evolved_variables=fields.evolved_variables,
            playbook=fields.playbook,
            expected_updated_at=expected_updated_at,
        )
        return entry.id
