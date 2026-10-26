from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.application.ports.configuration_deploy_request_port import (
    ConfigurationDeployRequestRepository,
)
from src.application.ports.configuration_port import ConfigurationRepository
from src.domain.configurations.entities import ConfigurationRecord


@dataclass(frozen=True)
class ConfigurationGraphNode:
    record: ConfigurationRecord
    # Message of the approved deploy request that promoted this version;
    # None when it never reached production or was activated without one.
    promotion_comment: str | None = None


class GetConfigurationGraphUseCase:
    """Every immutable version, oldest first, for the read-only version graph."""

    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        deploy_request_repository: ConfigurationDeployRequestRepository,
    ) -> None:
        self._configurations = configuration_repository
        self._deploy_requests = deploy_request_repository

    def execute(self) -> list[ConfigurationGraphNode]:
        comments: dict[tuple[str, int], tuple[datetime, str]] = {}
        for request in self._deploy_requests.list():
            if request.status != "approved" or request.approved_at is None:
                continue
            key = (request.target_configuration_id, request.target_version)
            latest = comments.get(key)
            if latest is None or request.approved_at > latest[0]:
                comments[key] = (request.approved_at, request.message)
        records = sorted(
            self._configurations.list_all_versions(),
            key=lambda config: (
                config.created_at,
                config.configuration_id,
                config.version,
            ),
        )
        return [
            ConfigurationGraphNode(
                record=record,
                promotion_comment=(
                    comments[(record.configuration_id, record.version)][1]
                    if record.ever_activated
                    and (record.configuration_id, record.version) in comments
                    else None
                ),
            )
            for record in records
        ]
