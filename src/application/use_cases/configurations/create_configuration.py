from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.ports.configuration_port import (
    ConfigurationRecord,
    ConfigurationRepository,
)
from src.application.use_cases.configurations.index_configuration_knowledge import (
    IndexConfigurationKnowledgeUseCase,
)


class CreateConfigurationUseCase:
    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        index_configuration_knowledge: IndexConfigurationKnowledgeUseCase,
    ) -> None:
        self._configurations = configuration_repository
        self._index_configuration_knowledge = index_configuration_knowledge

    def execute(self, input: CreateConfigurationInput) -> ConfigurationRecord:
        if input.configuration_id is not None:
            latest = self._configurations.get_latest_version(input.configuration_id)
            configuration_id = input.configuration_id
            version = latest.version + 1 if latest is not None else 1
        else:
            configuration_id = str(uuid.uuid4())
            version = 1

        now = datetime.now(timezone.utc)
        record = ConfigurationRecord(
            configuration_id=configuration_id,
            version=version,
            name=input.name,
            description=input.description,
            # Never active on creation - activation is a separate, explicit
            # step so the single-active invariant is only ever touched by
            # ActivateConfigurationUseCase.
            active=False,
            general=input.general,
            infra=input.infra,
            ops=input.ops,
            monitoring=input.monitoring,
            agent=input.agent,
            test=input.test,
            created_at=now,
            updated_at=now,
            created_by=input.created_by,
        )
        created = self._configurations.create(record)
        self._index_configuration_knowledge.execute(created)
        return created
