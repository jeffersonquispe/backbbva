from __future__ import annotations

from src.application.ports.configuration_port import ResolutionTag
from src.application.ports.resolution_method_catalog_port import (
    ResolutionMethod,
    ResolutionMethodCatalogRepository,
)


class ResolutionMethodNotFoundError(Exception):
    pass


class UpdateResolutionMethodUseCase:
    def __init__(
        self, resolution_method_catalog_repository: ResolutionMethodCatalogRepository
    ) -> None:
        self._methods = resolution_method_catalog_repository

    def execute(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        resolution_tag: ResolutionTag | None = None,
        active: bool | None = None,
    ) -> ResolutionMethod:
        updated = self._methods.update(
            entry_id, value=value, resolution_tag=resolution_tag, active=active
        )
        if updated is None:
            raise ResolutionMethodNotFoundError(
                f"Resolution method not found: {entry_id}"
            )
        return updated
