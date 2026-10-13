from __future__ import annotations

from uuid import UUID

from src.domain import DomainException


class ModelNotFoundError(DomainException):
    def __init__(self, model_id: UUID) -> None:
        self.model_id = model_id
        super().__init__(f"Model {model_id} not found.")


class ModelAlreadyTrainingError(DomainException):
    def __init__(self, model_id: UUID) -> None:
        self.model_id = model_id
        super().__init__(f"Model {model_id} is already training.")
