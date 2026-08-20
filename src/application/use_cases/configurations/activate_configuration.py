from __future__ import annotations

from dataclasses import replace

from src.application.ports.configuration_port import (
    ConfigurationRecord,
    ConfigurationRepository,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)


class ConfigurationNotFoundError(Exception):
    pass


class ActivateConfigurationUseCase:
    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        fraud_knowledge_repository: FraudKnowledgeRepository,
    ) -> None:
        self._configurations = configuration_repository
        self._fraud_knowledge = fraud_knowledge_repository

    def execute(self, configuration_id: str, version: int) -> ConfigurationRecord:
        if self._configurations.get(configuration_id, version) is None:
            raise ConfigurationNotFoundError(
                f"Configuration {configuration_id} v{version} not found"
            )

        previous_active = self._configurations.get_active()
        activated = self._configurations.activate(configuration_id, version)

        # ponytail: per-document loop, not a bulk update_by_query - no
        # other repository in this codebase uses bulk ops, and a
        # configuration's knowledge set is small (reference data, not
        # per-alert volume). Mirrors the same choice made for the
        # DynamoDB side, see DynamoConfigurationRepository.activate.
        if previous_active is not None and (
            previous_active.configuration_id,
            previous_active.version,
        ) != (configuration_id, version):
            self._set_documents_active(
                previous_active.configuration_id, previous_active.version, False
            )
        self._set_documents_active(configuration_id, version, True)

        return activated

    def _set_documents_active(
        self, configuration_id: str, version: int, active: bool
    ) -> None:
        documents = self._fraud_knowledge.list(
            configuration=configuration_id, version=version
        )
        for document in documents:
            self._fraud_knowledge.update(replace(document, activate=active))
