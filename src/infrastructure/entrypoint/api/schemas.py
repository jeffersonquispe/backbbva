from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.configuration_port import (
    SamplingIntervalUnit,
    ShortageAction,
    TestCleanupPolicy,
)
from src.application.ports.dataset_analysis_port import DatasetAnalysisStatus
from src.application.ports.test_run_port import TestRunStatus
from src.application.ports.workflow_port import WorkflowStatus, WorkflowStepStatus


class CreateAsyncOperationRequest(BaseModel):
    operation_type: str = Field(..., min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=120)


class UpdateAsyncOperationRequest(BaseModel):
    status: AsyncOperationStatus | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class AsyncOperationResponse(BaseModel):
    id: UUID
    operation_type: str
    status: AsyncOperationStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    dispatched_at: datetime | None
    execution_backend: str | None
    external_id: str | None


class AsyncOperationPollingResponse(BaseModel):
    id: UUID
    status: AsyncOperationStatus
    done: bool
    retry_after_seconds: int | None
    result: dict[str, Any] | None
    error: str | None
    updated_at: datetime


class ReconcileAsyncOperationsRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


class ReconciledAsyncOperationResponse(BaseModel):
    id: UUID
    previous_status: AsyncOperationStatus
    current_status: AsyncOperationStatus
    execution_state: AsyncExecutionState
    detail: str | None


class ReconcileAsyncOperationsResponse(BaseModel):
    inspected: int
    updated: int
    operations: list[ReconciledAsyncOperationResponse]


class TestRunConfigRequest(BaseModel):
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    model_overrides: dict[str, str] = Field(default_factory=dict)


class StartTestRunRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    dataset_name: str = Field(..., min_length=1)
    config: TestRunConfigRequest = Field(default_factory=TestRunConfigRequest)
    # Both unset = dispatch every row (unchanged default). sample_size
    # alone = stratify by the dataset's own no-risk/risk-suspected/risk
    # proportions. Both set = stratify by these exact proportions instead
    # (e.g. a class-balanced sample). Keys must be "no-risk",
    # "risk-suspected", "risk", summing to 1.0.
    sample_size: int | None = Field(default=None, gt=0)
    sample_distribution: dict[str, float] | None = None


class StartTestRunResponse(BaseModel):
    test_run_id: UUID
    dispatched_count: int


class TestRunResponse(BaseModel):
    id: UUID
    name: str
    dataset_name: str
    status: TestRunStatus
    total: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class TestCaseSummaryResponse(BaseModel):
    workflow_execution_id: UUID
    alert_id: UUID
    status: WorkflowStatus
    current_step: str | None


class TestRunDetailResponse(BaseModel):
    id: UUID
    name: str
    dataset_name: str
    config: TestRunConfigRequest
    status: TestRunStatus
    total: int
    succeeded: int
    failed: int
    running: int
    pending: int
    input_tokens: int
    output_tokens: int
    cases: list[TestCaseSummaryResponse]


class WorkflowStepResponse(BaseModel):
    id: UUID
    step_name: str
    status: WorkflowStepStatus
    attempt: int
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class TestCaseDetailResponse(BaseModel):
    workflow_execution_id: UUID
    alert_id: UUID
    status: WorkflowStatus
    input_tokens: int
    output_tokens: int
    steps: list[WorkflowStepResponse]


class DatasetResponse(BaseModel):
    name: str
    row_count: int


class UploadDatasetResponse(BaseModel):
    name: str
    status: DatasetAnalysisStatus


class DeleteDatasetResponse(BaseModel):
    name: str
    deleted: bool


class FieldDistributionResponse(BaseModel):
    value: str
    count: int
    percentage: float


class DatasetSummaryResponse(BaseModel):
    dataset_name: str
    status: DatasetAnalysisStatus
    total_rows: int
    field_distributions: dict[str, list[FieldDistributionResponse]]
    uploaded_at: datetime | None
    updated_at: datetime | None
    error: str | None


# --- Configuration -----------------------------------------------------
# One schema class per sub-configuration group, reused for both request
# and response bodies (request fields all have defaults; responses are
# always fully populated) - avoids a duplicate Request/Response pair per
# group. Field-for-field mirror of application/ports/configuration_port.py,
# itself mirroring frontend_mockup/src/data/configs.ts's ConfigSettings.


class TaxonomySchema(BaseModel):
    id: str = ""
    code: str
    name: str
    description: str = ""
    variables: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    active: bool = True
    segmento: str = ""


class ModusOperandiSchema(BaseModel):
    id: str = ""
    title: str
    narrative: str = ""
    taxonomy_id: str
    segmento: str = ""


class RedFlagSchema(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    modus_operandi_id: str
    taxonomy_id: str
    variables: list[str] = Field(default_factory=list)
    segmento: str = ""


class YellowFlagSchema(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    modus_operandi_id: str
    taxonomy_id: str
    variables: list[str] = Field(default_factory=list)
    segmento: str = ""


class ExampleCaseSchema(BaseModel):
    id: str = ""
    text: str
    modus_operandi_id: str
    taxonomy_id: str
    segmento: str = ""


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
        DayProfileSchema(
            id="regular",
            name="Día regular",
            description="Cobertura estándar para días hábiles sin eventos especiales.",
            hourly=[4] * 24,
        ),
        DayProfileSchema(
            id="pago",
            name="Día de pago",
            description="Refuerzo por mayor volumen de alertas en fechas de pago.",
            hourly=[8] * 24,
        ),
    ]


class AnalystCapacitySchema(BaseModel):
    profiles: list[DayProfileSchema] = Field(
        default_factory=_default_analyst_profile_schemas
    )
    default_profile_id: str = "regular"
    day_overrides: dict[int, str] = Field(
        default_factory=lambda: {15: "pago", 20: "pago", 30: "pago"}
    )


class ShortageBehaviorSchema(BaseModel):
    action: ShortageAction = ShortageAction.BLOCK_SOFT
    custom_text: str = ""


class GeneralSettingsSchema(BaseModel):
    agent_enabled: bool = True
    migration_window_enabled: bool = False
    migration_window_hour: int = Field(default=2, ge=0, le=23)


class InfraSettingsSchema(BaseModel):
    max_instances: int = 8
    auto_scale: bool = True


class OpsSettingsSchema(BaseModel):
    voicebot_max_concurrent_calls: int = 40
    analyst_capacity: AnalystCapacitySchema = Field(
        default_factory=AnalystCapacitySchema
    )
    queue_max_lifetime_value: int = 60
    queue_max_lifetime_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    voicebot_shortage_behavior: ShortageBehaviorSchema = Field(
        default_factory=ShortageBehaviorSchema
    )
    analyst_shortage_behavior: ShortageBehaviorSchema = Field(
        default_factory=ShortageBehaviorSchema
    )


class MonitoringSettingsSchema(BaseModel):
    sampling_interval_value: int = 30
    sampling_interval_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    sampling_criteria: list[SamplingCriterionSchema] = Field(default_factory=list)
    max_samples: int = 200
    prompt_clasificacion: str = ""
    prompt_analista: str = ""
    prompt_monitoreo: str = ""
    evaluation_variables: list[str] = Field(default_factory=list)


class AgentSettingsSchema(BaseModel):
    perfil_usuario: str = ""
    perfil_usuario_vars: list[str] = Field(default_factory=list)
    perfil_transaccion: str = ""
    perfil_transaccion_vars: list[str] = Field(default_factory=list)
    perfil_transaccional: str = ""
    perfil_transaccional_vars: list[str] = Field(default_factory=list)
    taxonomies: list[TaxonomySchema] = Field(default_factory=list)
    modus_operandi: list[ModusOperandiSchema] = Field(default_factory=list)
    red_flags: list[RedFlagSchema] = Field(default_factory=list)
    yellow_flags: list[YellowFlagSchema] = Field(default_factory=list)
    example_cases: list[ExampleCaseSchema] = Field(default_factory=list)
    active_fields: list[str] = Field(default_factory=list)


class TestSettingsSchema(BaseModel):
    max_test_instances: int = 4
    max_concurrent_experiments: int = 3
    experiment_timeout_minutes: int = 30
    max_stored_test_runs: int = 20
    test_cleanup_policy: TestCleanupPolicy = TestCleanupPolicy.OLDEST


class CreateConfigurationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    # Omit for a brand-new configuration (fresh id, version 1). Set to an
    # existing configuration_id to append a new version to that lineage.
    configuration_id: str | None = None
    description: str = ""
    general: GeneralSettingsSchema = Field(default_factory=GeneralSettingsSchema)
    infra: InfraSettingsSchema = Field(default_factory=InfraSettingsSchema)
    ops: OpsSettingsSchema = Field(default_factory=OpsSettingsSchema)
    monitoring: MonitoringSettingsSchema = Field(
        default_factory=MonitoringSettingsSchema
    )
    agent: AgentSettingsSchema = Field(default_factory=AgentSettingsSchema)
    test: TestSettingsSchema = Field(default_factory=TestSettingsSchema)
    created_by: str | None = Field(default=None, max_length=120)


class ConfigurationSummaryResponse(BaseModel):
    configuration_id: str
    version: int
    name: str
    description: str
    active: bool
    created_at: datetime
    updated_at: datetime


class ConfigurationDetailResponse(ConfigurationSummaryResponse):
    general: GeneralSettingsSchema
    infra: InfraSettingsSchema
    ops: OpsSettingsSchema
    monitoring: MonitoringSettingsSchema
    agent: AgentSettingsSchema
    test: TestSettingsSchema
    created_by: str | None
