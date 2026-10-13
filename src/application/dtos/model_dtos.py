from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from src.application.ports.model_port import (
    FieldTransform,
    HistoricalFeature,
    ModelStatus,
    TrainingConfig,
)


@dataclass
class CreateModelInput:
    tag: str
    description: str
    dataset_name: str
    target_field: str
    positive_labels: list[str] = field(default_factory=list)
    feature_transforms: list[FieldTransform] = field(default_factory=list)
    created_by: str | None = None
    historical_features: list[HistoricalFeature] = field(default_factory=list)
    feature_configuration: dict[str, Any] | None = None
    training_config: TrainingConfig = field(default_factory=TrainingConfig)


@dataclass
class ModelOutput:
    id: UUID
    tag: str
    description: str
    status: ModelStatus
    dataset_name: str
    target_field: str
    positive_labels: list[str]
    feature_transforms: list[FieldTransform]
    active: bool
    metrics: dict[str, float] | None
    storage_ref: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    error: str | None
    historical_features: list[HistoricalFeature] = field(default_factory=list)
    feature_configuration: dict[str, Any] | None = None
    training_config: TrainingConfig = field(default_factory=TrainingConfig)
    training_report: dict[str, Any] | None = None


@dataclass
class StartModelTrainingOutput:
    async_operation_id: UUID
    model_id: UUID
