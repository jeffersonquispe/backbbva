from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.configurations.entities import (
    FilterConditionOperator,
    LogicalOperator,
    ResolutionTag,
    SamplingIntervalUnit,
    TagCategory,
    TestCleanupPolicy,
)
from src.infrastructure.entrypoint.api.schemas.configuration_agent import (
    AgentSettingsSchema,
)


class DistributionValueSchema(BaseModel):
    id: str
    label: str
    pct: int


class SamplingCriterionSchema(BaseModel):
    id: str
    name: str
    values: list[DistributionValueSchema] = Field(default_factory=list)


class DayProfileSchema(BaseModel):
    id: str
    name: str
    description: str = ""
    hourly: list[int] = Field(default_factory=lambda: [0] * 24)


def _default_analyst_profile_schemas() -> list[DayProfileSchema]:
    return [
        DayProfileSchema(id="regular", name="Día regular", description="Cobertura estándar para días hábiles sin eventos especiales.", hourly=[4] * 24),
        DayProfileSchema(id="pago", name="Día de pago", description="Refuerzo por mayor volumen de alertas en fechas de pago.", hourly=[8] * 24),
    ]


class AnalystCapacitySchema(BaseModel):
    profiles: list[DayProfileSchema] = Field(default_factory=_default_analyst_profile_schemas)
    default_profile_id: str = "regular"
    day_overrides: dict[int, str] = Field(default_factory=lambda: {15: "pago", 20: "pago", 30: "pago"})


class ShortageBehaviorSchema(BaseModel):
    resolution_tag: ResolutionTag = ResolutionTag.BLOCK_SOFT
    resolution_method_id: str | None = None


class GeneralSettingsSchema(BaseModel):
    migration_window_enabled: bool = False
    migration_window_datetime: str = "2000-01-01T02:00"
    llm_selection: dict[str, str | None] = Field(default_factory=dict)


class InfraSettingsSchema(BaseModel):
    max_instances: int = 8
    auto_scale: bool = True
    fraud_history_db_retention_days: int = Field(default=90, ge=1)
    fraud_history_cold_storage_retention_months: int = Field(default=24, ge=1)


class MonitoringSettingsSchema(BaseModel):
    sampling_interval_value: int = 30
    sampling_interval_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    sampling_criteria: list[SamplingCriterionSchema] = Field(default_factory=list)
    max_samples: int = 200
    prompt_clasificacion: str = ""
    prompt_clasificacion_vars: list[str] = Field(default_factory=list)
    prompt_analista: str = ""
    prompt_analista_vars: list[str] = Field(default_factory=list)
    prompt_monitoreo: str = ""
    prompt_monitoreo_vars: list[str] = Field(default_factory=list)


class TestSettingsSchema(BaseModel):
    max_test_instances: int = 4
    max_concurrent_experiments: int = 3
    experiment_timeout_minutes: int = 30
    max_stored_test_runs: int = 20
    test_cleanup_policy: TestCleanupPolicy = TestCleanupPolicy.OLDEST


class FilterConditionSchema(BaseModel):
    id: str = ""
    category: TagCategory
    operator: FilterConditionOperator = FilterConditionOperator.IN
    values: list[str] = Field(default_factory=list)


class FilterGroupSchema(BaseModel):
    id: str = ""
    operator: LogicalOperator = LogicalOperator.AND
    conditions: list[FilterConditionSchema] = Field(default_factory=list)
    groups: list[FilterGroupSchema] = Field(default_factory=list)


FilterGroupSchema.model_rebuild()


class SegmentSettingsSchema(BaseModel):
    enabled: bool = False
    filter: FilterGroupSchema = Field(default_factory=lambda: FilterGroupSchema(id="root"))
    monitoring: MonitoringSettingsSchema = Field(default_factory=MonitoringSettingsSchema)
    agent: AgentSettingsSchema = Field(default_factory=AgentSettingsSchema)
    order: int = 0
