from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
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
class HistoricalFeature:
    name: str
    field: str = "transacciones_json"
    reference_field: str = "fecha_transaccion"
    time_field: str = "eventtime"
    value_field: str = "amount_value"
    operation: str = "count"
    window_hours: int = 24
    filter_field: str | None = None
    filter_value: str | None = None
    compare_field: str | None = None


@dataclass
class TrainingConfig:
    n_estimators: int = 400
    max_depth: int = 4
    learning_rate: float = 0.03
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_lambda: float = 1.0
    min_child_weight: float = 3.0
    scale_pos_weight: float | None = None
    early_stopping_rounds: int | None = 30
    split_strategy: str = "stratified"
    time_field: str = "fecha_transaccion"
    timezone: str = "UTC"


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
    historical_features: list[HistoricalFeature] = field(default_factory=list)
    feature_configuration: dict[str, Any] | None = None
    training_config: TrainingConfig = field(default_factory=TrainingConfig)
    training_report: dict[str, Any] | None = None


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
