from __future__ import annotations

from uuid import UUID

from src.application.dtos.model_dtos import ModelOutput
from src.application.ports.model_port import ModelRepository
from src.application.use_cases.models.create_model import _to_output


class GetModelUseCase:
    def __init__(self, repository: ModelRepository) -> None:
        self._repository = repository

    def execute(self, model_id: UUID) -> ModelOutput | None:
        model = self._repository.get(model_id)
        if model is None:
            return None
        return _to_output(model)
