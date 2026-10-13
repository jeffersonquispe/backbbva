from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.ports.marcacion_catalog_port import (
    MarcacionCatalogRepository,
    MarcacionCategory,
    RiskLabel,
)


class CreateMarcacionCategoryUseCase:
    def __init__(
        self, marcacion_catalog_repository: MarcacionCatalogRepository
    ) -> None:
        self._categories = marcacion_catalog_repository

    def execute(self, value: str, risk_label: RiskLabel) -> MarcacionCategory:
        now = datetime.now(UTC)
        return self._categories.create(
            MarcacionCategory(
                id=str(uuid.uuid4()),
                value=value,
                risk_label=risk_label,
                created_at=now,
                updated_at=now,
            )
        )
