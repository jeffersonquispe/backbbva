from __future__ import annotations

from uuid import UUID

from src.application.ports.model_port import ModelRepository


class DeleteModelUseCase:
    def __init__(self, repository: ModelRepository) -> None:
        self._repository = repository

    def execute(self, model_id: UUID) -> None:
        self._repository.delete(model_id)
