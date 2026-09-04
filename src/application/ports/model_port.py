from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ModelStatus(StrEnum):
    DRAFT = "DRAFT"
    TRAINING = "TRAINING"
    READY = "READY"
    FAILED = "FAILED"


class FieldTransformKind(StrEnum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    # Derives hour/day-of-week/month from the field, plus a day-delta
    # against reference_field when set.
    DATE_DERIVED = "date_derived"
    # Tokenizes a list-like field and materializes multi-hot columns for
    # its top_n most frequent tokens (vocabulary is fit at train time and
    # persisted in the model bundle so scoring reproduces the same columns).
    RULE_MULTIHOT = "rule_multihot"
    DROP = "drop"


@dataclass
class FieldTransform:
    field: str
    kind: FieldTransformKind
    reference_field: str | None = None
    top_n: int = 30


@dataclass
class ModelRecord:
    id: UUID
    tag: str
    description: str
    status: ModelStatus
    dataset_name: str
    target_field: str
    positive_labels: list[str] = field(default_factory=list)
    feature_transforms: list[FieldTransform] = field(default_factory=list)
    active: bool = False
    metrics: dict[str, float] | None = None
    storage_ref: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str | None = None
    error: str | None = None


class ModelRepository(Protocol):
    def create(self, model: ModelRecord) -> ModelRecord:
        ...

    def get(self, model_id: UUID) -> ModelRecord | None:
        ...

    def list(self) -> list[ModelRecord]:
        ...

    def get_active(self) -> ModelRecord | None:
        ...

    def update(self, model: ModelRecord) -> ModelRecord:
        ...

    def activate(self, model_id: UUID) -> ModelRecord:
        ...

    def delete(self, model_id: UUID) -> None:
        ...
