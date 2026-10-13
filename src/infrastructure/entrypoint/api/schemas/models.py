from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from src.application.ports.model_port import (
    FieldTransformKind as ModelFieldTransformKind,
)
from src.application.ports.model_port import (
    ModelStatus,
)

# --- Models (XGBoost training) ------------------------------------------


class FieldTransformRequest(BaseModel):
    field: str = Field(..., min_length=1)
    kind: ModelFieldTransformKind
    reference_field: str | None = None
    top_n: int = Field(default=30, ge=1, le=200)


class FieldTransformResponse(BaseModel):
    field: str
    kind: ModelFieldTransformKind
    reference_field: str | None
    top_n: int


class HistoricalFeatureRequest(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
    field: str = Field(default="transacciones_json", min_length=1)
    reference_field: str = Field(default="fecha_transaccion", min_length=1)
    time_field: str = Field(default="eventtime", min_length=1)
    value_field: str = Field(default="amount_value", min_length=1)
    operation: Literal[
        "count", "sum", "median", "mean", "max", "distinct", "recency"
    ] = "count"
    window_hours: int = Field(default=24, ge=1, le=2160)
    filter_field: Literal["tipo_transaccion", "integrationpoint", "canal"] | None = None
    filter_value: str | None = None
    compare_field: str | None = None

    @model_validator(mode="after")
    def validate_recipe(self):
        if bool(self.filter_field) != bool(self.filter_value):
            raise ValueError("El filtro necesita campo y valor")
        if self.compare_field and self.operation not in (
            "sum",
            "median",
            "mean",
            "max",
        ):
            raise ValueError("La comparación solo admite agregaciones de importe")
        return self


class TrainingConfigRequest(BaseModel):
    n_estimators: int = Field(default=400, ge=1, le=5000)
    max_depth: int = Field(default=4, ge=1, le=16)
    learning_rate: float = Field(default=0.03, ge=0.001, le=1, allow_inf_nan=False)
    subsample: float = Field(default=0.8, ge=0.1, le=1, allow_inf_nan=False)
    colsample_bytree: float = Field(default=0.8, ge=0.1, le=1, allow_inf_nan=False)
    reg_lambda: float = Field(default=1, ge=0, le=100, allow_inf_nan=False)
    min_child_weight: float = Field(default=3, ge=0, le=100, allow_inf_nan=False)
    scale_pos_weight: float | None = Field(
        default=None, gt=0, le=100000, allow_inf_nan=False
    )
    early_stopping_rounds: int | None = Field(default=30, ge=1, le=500)
    split_strategy: Literal["temporal", "stratified"] = "stratified"
    time_field: str = Field(default="fecha_transaccion", min_length=1)
    timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_timezone(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Zona horaria IANA no válida")
        return self


class CreateModelRequest(BaseModel):
    tag: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    dataset_name: str = Field(..., min_length=1)
    target_field: str = Field(..., min_length=1)
    positive_labels: list[str] = Field(default_factory=list)
    feature_transforms: list[FieldTransformRequest] = Field(default_factory=list)
    created_by: str | None = None
    historical_features: list[HistoricalFeatureRequest] = Field(
        default_factory=list, max_length=100
    )
    feature_configuration: dict[str, Any] | None = None
    training_config: TrainingConfigRequest = Field(
        default_factory=TrainingConfigRequest
    )

    @model_validator(mode="after")
    def validate_features(self):
        if (
            not self.tag.strip()
            or not self.positive_labels
            or any(not p.strip() for p in self.positive_labels)
        ):
            raise ValueError("Indica nombre y al menos una etiqueta positiva")
        included = [f for f in self.feature_transforms if f.kind.value != "drop"]
        if self.feature_configuration is not None:
            from src.domain.models.feature_recipe import validate_feature_definition

            self.feature_configuration = validate_feature_definition(
                self.feature_configuration, forbidden_paths=(self.target_field,)
            )
        enabled_recipes = [
            r
            for r in (self.feature_configuration or {}).get("recipes", [])
            if r.get("enabled", True)
        ]
        if not included and not self.historical_features and not enabled_recipes:
            raise ValueError("Incluye al menos una característica")
        names = (
            [f.field for f in included]
            + [f"history__{f.name}" for f in self.historical_features]
            + [r["name"] for r in enabled_recipes]
        )
        if len(set(names)) != len(names):
            raise ValueError("Los nombres de características deben ser únicos")
        sources = [f.field for f in included] + [f.reference_field for f in included]
        for f in self.historical_features:
            sources.extend([f.field, f.reference_field, f.compare_field])
        if any(
            source
            and (
                source == self.target_field
                or self.target_field.startswith(source + ".")
                or source.startswith(self.target_field + ".")
            )
            for source in sources
        ):
            raise ValueError(
                "El objetivo no puede usarse como característica ni referencia"
            )
        return self


class ModelResponse(BaseModel):
    id: UUID
    tag: str
    description: str
    status: ModelStatus
    dataset_name: str
    target_field: str
    positive_labels: list[str]
    feature_transforms: list[FieldTransformResponse]
    active: bool
    metrics: dict[str, float] | None
    storage_ref: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    error: str | None

    historical_features: list[HistoricalFeatureRequest] = Field(default_factory=list)
    feature_configuration: dict[str, Any] | None = None
    training_config: TrainingConfigRequest = Field(
        default_factory=TrainingConfigRequest
    )
    training_report: dict[str, Any] | None = None


class StartModelTrainingResponse(BaseModel):
    async_operation_id: UUID
    model_id: UUID


class DeleteModelResponse(BaseModel):
    id: UUID
    deleted: bool
