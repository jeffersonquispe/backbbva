from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.ports.configuration_port import ResolutionTag
from src.application.ports.resolution_method_catalog_port import (
    ResolutionMethod,
    ResolutionMethodCatalogRepository,
)


class CreateResolutionMethodUseCase:
    def __init__(
        self, resolution_method_catalog_repository: ResolutionMethodCatalogRepository
    ) -> None:
        self._methods = resolution_method_catalog_repository

    def execute(self, value: str, resolution_tag: ResolutionTag) -> ResolutionMethod:
        now = datetime.now(UTC)
        return self._methods.create(
            ResolutionMethod(
                id=str(uuid.uuid4()),
                value=value,
                resolution_tag=resolution_tag,
                created_at=now,
                updated_at=now,
            )
        )
