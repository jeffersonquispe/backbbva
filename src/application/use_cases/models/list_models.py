from __future__ import annotations

from src.application.dtos.model_dtos import ModelOutput
from src.application.ports.model_port import ModelRepository
from src.application.use_cases.models.create_model import _to_output


class ListModelsUseCase:
    def __init__(self, repository: ModelRepository) -> None:
        self._repository = repository

    def execute(self) -> list[ModelOutput]:
        return [_to_output(model) for model in self._repository.list()]
