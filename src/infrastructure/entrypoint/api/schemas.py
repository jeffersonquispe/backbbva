from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportStatus,
)
from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.configuration_port import (
    DocumentationStrategy,
    FilterConditionOperator,
    FlagType,
    ListMembershipMode,
    LogicalOperator,
    ProfilingPromptMode,
    ProfilingStrategyKey,
    ResolutionTag,
    SamplingIntervalUnit,
    TestCleanupPolicy,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
)
from src.application.ports.marcacion_catalog_port import RiskLabel
from src.application.ports.model_port import (
    FieldTransformKind as ModelFieldTransformKind,
    ModelStatus,
)
from src.application.ports.simulation_scenario_port import (
    GeneratorKind,
    OutputMode,
    ScenarioStatus,
)
from src.application.ports.watchlist_port import WatchlistType
from src.application.ports.tag_catalog_port import TagCategory
from src.application.ports.test_run_port import TestRunStatus
from src.application.ports.workflow_port import WorkflowStatus, WorkflowStepStatus
from src.application.ports.vector_store_instance_port import KnowledgeAssetType


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


class ConfigurationRefRequest(BaseModel):
    configuration_id: str
    # None = that lineage's latest version.
    version: int | None = None


class TestRunConfigRequest(BaseModel):
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    model_overrides: dict[str, str] = Field(default_factory=dict)
    # How many classification<->adversarial feedback loops a case gets
    # before escalating to an analyst - see WorkflowExecutionRecord.
    # max_feedback_iterations.
    max_feedback_iterations: int = Field(default=1, ge=0)
    # Pin this test run to one specific (possibly inactive)
    # ConfigurationRecord instead of the currently-active one - lets
    # multiple test runs each target a different configuration
    # concurrently without touching the global active flag.
    configuration_ref: ConfigurationRefRequest | None = None


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
    # Nested (not a flattened configuration_ref field) so this matches the
    # same test_run.config -> TestRunConfigRequest attribute pass-through
    # TestRunDetailResponse already relies on below - configuration_ref is
    # None when this run tested the active configuration at dispatch time
    # (today's only behavior before ConfigurationRef existed). See
    # TestRunConfig.configuration_ref (test_run_port.py).
    config: TestRunConfigRequest


class TestCaseSummaryResponse(BaseModel):
    workflow_execution_id: UUID
    alert_id: UUID
    status: WorkflowStatus
    current_step: str | None
    duration_seconds: float | None


class DurationStatsResponse(BaseModel):
    count: int
    min_seconds: float
    max_seconds: float
    avg_seconds: float
    p95_seconds: float


class ClassMetricsResponse(BaseModel):
    precision: float
    recall: float
    f1: float
    support: int


class ClassificationMetricsResponse(BaseModel):
    per_class: dict[str, ClassMetricsResponse]
    macro_precision: float
    macro_recall: float
    macro_f1: float
    confusion_matrix: dict[str, dict[str, int]]
    total: int


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
    step_duration_stats: dict[str, DurationStatsResponse]
    total_duration_stats: DurationStatsResponse | None
    analyst_agreement_metrics: ClassificationMetricsResponse | None
    ground_truth_metrics: ClassificationMetricsResponse | None


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


class DeleteTestRunsRequest(BaseModel):
    test_run_ids: list[UUID] = Field(..., min_length=1)


class DeleteTestRunsResponse(BaseModel):
    deleted_test_runs: int
    deleted_cases: int


class DatasetResponse(BaseModel):
    name: str
    row_count: int


class UploadDatasetResponse(BaseModel):
    name: str
    status: DatasetAnalysisStatus
    async_operation_id: UUID | None = None


class DeleteDatasetResponse(BaseModel):
    name: str
    deleted: bool
    async_operation_id: UUID | None = None


class FieldDistributionResponse(BaseModel):
    value: str
    count: int
    percentage: float


class FraudMaturationProfileResponse(BaseModel):
    sample_size: int
    avg_days: float | None
    min_days: float | None
    max_days: float | None
    p95_days: float | None


class FraudMarkingAnalysisResponse(BaseModel):
    dataset_name: str
    evaluated_rows: int
    skipped_rows: int
    false_positives: int
    false_negatives: int
    properly_marked: int
    maturation: FraudMaturationProfileResponse


class FraudMarkingAnalysisQueuedResponse(BaseModel):
    dataset_name: str
    status: Literal["PENDING"] = "PENDING"
    async_operation_id: UUID


class DatasetSummaryResponse(BaseModel):
    dataset_name: str
    status: DatasetAnalysisStatus
    total_rows: int
    field_distributions: dict[str, list[FieldDistributionResponse]]
    available_fields: list[str]
    uploaded_at: datetime | None
    updated_at: datetime | None
    error: str | None
    origin: DatasetOrigin
    source_dataset_names: list[str]
    extraction_filter: dict[str, str] | None
    fraud_marking_analysis: FraudMarkingAnalysisResponse | None = None


class CreateEmptyDatasetRequest(BaseModel):
    name: str = Field(..., min_length=1)
    fields: list[str] = Field(..., min_length=1)


class ExtractDatasetRequest(BaseModel):
    source_names: list[str] = Field(..., min_length=1)
    filters: dict[str, str] = Field(default_factory=dict)
    percentage: float = Field(..., gt=0, le=100)
    target_name: str = Field(..., min_length=1)


class AppendDatasetRowsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(..., min_length=1)


class AppendDatasetRowsResponse(BaseModel):
    name: str
    total_rows: int
    status: DatasetAnalysisStatus


class DatasetRowsResponse(BaseModel):
    rows: list[dict[str, Any]]
    total: int


class CurateAlertToDatasetRequest(BaseModel):
    dataset_name: str = Field(..., min_length=1)
    justification: str = Field(..., min_length=1)
    # Manual override of the configuration/version this curation's
    # Feedback record attributes to - when omitted, the use case tries to
    # auto-detect it from the alert's own workflow execution, and raises
    # ValueError (mapped to 400 below) if neither is available.
    configuration_id: str | None = None
    version: int | None = None


class CurateAlertToDatasetResponse(BaseModel):
    dataset_name: str
    total_rows: int
    status: DatasetAnalysisStatus
    feedback_id: UUID
    configuration_id: str
    version: int


class AlertFieldMappingResponse(BaseModel):
    dataset_name: str
    mappings: dict[str, str]
    updated_at: datetime | None


class SaveAlertFieldMappingRequest(BaseModel):
    mappings: dict[str, str]


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
    operation: Literal["count", "sum", "median", "mean", "max", "distinct", "recency"] = "count"
    window_hours: int = Field(default=24, ge=1, le=2160)
    filter_field: Literal["tipo_transaccion", "integrationpoint", "canal"] | None = None
    filter_value: str | None = None
    compare_field: str | None = None

    @model_validator(mode="after")
    def validate_recipe(self):
        if bool(self.filter_field) != bool(self.filter_value):
            raise ValueError("El filtro necesita campo y valor")
        if self.compare_field and self.operation not in ("sum", "median", "mean", "max"):
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
    scale_pos_weight: float | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
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
    historical_features: list[HistoricalFeatureRequest] = Field(default_factory=list, max_length=100)
    feature_configuration: dict[str, Any] | None = None
    training_config: TrainingConfigRequest = Field(default_factory=TrainingConfigRequest)

    @model_validator(mode="after")
    def validate_features(self):
        if not self.tag.strip() or not self.positive_labels or any(not p.strip() for p in self.positive_labels):
            raise ValueError("Indica nombre y al menos una etiqueta positiva")
        included = [f for f in self.feature_transforms if f.kind.value != "drop"]
        if self.feature_configuration is not None:
            from src.domain.models.feature_recipe import validate_feature_definition
            self.feature_configuration = validate_feature_definition(self.feature_configuration, forbidden_paths=(self.target_field,))
        enabled_recipes = [r for r in (self.feature_configuration or {}).get("recipes", []) if r.get("enabled", True)]
        if not included and not self.historical_features and not enabled_recipes:
            raise ValueError("Incluye al menos una característica")
        names = [f.field for f in included] + [f"history__{f.name}" for f in self.historical_features] + [r["name"] for r in enabled_recipes]
        if len(set(names)) != len(names):
            raise ValueError("Los nombres de características deben ser únicos")
        sources = [f.field for f in included] + [f.reference_field for f in included]
        for f in self.historical_features:
            sources.extend([f.field, f.reference_field, f.compare_field])
        if any(source and (source == self.target_field or self.target_field.startswith(source + ".") or source.startswith(self.target_field + ".")) for source in sources):
            raise ValueError("El objetivo no puede usarse como característica ni referencia")
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
    training_config: TrainingConfigRequest = Field(default_factory=TrainingConfigRequest)
    training_report: dict[str, Any] | None = None


class StartModelTrainingResponse(BaseModel):
    async_operation_id: UUID
    model_id: UUID


class DeleteModelResponse(BaseModel):
    id: UUID
    deleted: bool


# --- Analyst capacity import --------------------------------------------
# Excel import for OperationalSettings.analyst_capacity -
# result only feeds the frontend's form until the admin saves it,
# see analyst_capacity_import_port.py.


class AnalystCapacityImportProfileSchema(BaseModel):
    id: str
    name: str
    description: str = ""
    hourly: list[int]


class UploadAnalystCapacityImportResponse(BaseModel):
    task_id: str
    status: AnalystCapacityImportStatus


class AnalystCapacityImportResponse(BaseModel):
    task_id: str
    status: AnalystCapacityImportStatus
    profiles: list[AnalystCapacityImportProfileSchema] = Field(default_factory=list)
    day_overrides: dict[int, str] = Field(default_factory=dict)
    error: str | None = None


# --- Configuration -----------------------------------------------------
# One schema class per sub-configuration group, reused for both request
# and response bodies (request fields all have defaults; responses are
# always fully populated) - avoids a duplicate Request/Response pair per
# group. Field-for-field mirror of application/ports/configuration_port.py
# and application/ports/tag_catalog_port.py, themselves mirroring
# frontend_mockup/src/data/configs.ts's ConfigSettings and the new
# segment/filter/tag-catalog types added alongside it.


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
    evolved_variables: list[str] = Field(default_factory=list)
    active: bool = True
    segmento: str = ""


class FlagSchema(BaseModel):
    id: str = ""
    flag_type: FlagType
    name: str
    description: str = ""
    evolved_variables: list[str] = Field(default_factory=list)
    modus_operandi_ids: list[str] = Field(default_factory=list)
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
    resolution_tag: ResolutionTag = ResolutionTag.BLOCK_SOFT
    resolution_method_id: str | None = None


class GeneralSettingsSchema(BaseModel):
    migration_window_enabled: bool = False
    migration_window_datetime: str = "2000-01-01T02:00"


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


class ProfilingStrategySchema(BaseModel):
    key: ProfilingStrategyKey
    main_prompt: str = ""
    main_prompt_vars: list[str] = Field(default_factory=list)
    main_prompt_mode: ProfilingPromptMode = ProfilingPromptMode.FSTRING
    categorization_prompt: str = ""
    categorization_prompt_vars: list[str] = Field(default_factory=list)
    use_pandas_history_mcp: bool = False


def _default_profiling_strategy_schemas() -> list[ProfilingStrategySchema]:
    return [ProfilingStrategySchema(key=key) for key in ProfilingStrategyKey]


def _default_field_enrichment_schema() -> dict[str, Any]:
    # Mirrors configuration_port.py's _default_field_enrichment - same
    # FeatureConfiguration shape models use (schema_version/mappings/
    # recipes), with "history" pre-mapped since this context always exposes
    # a single alert's transaction history under that fixed key.
    return {
        "schema_version": 2,
        "mappings": {"timezone": "America/Bogota", "history": "history"},
        "recipes": [],
    }


def _default_alert_filter_schema() -> dict[str, Any]:
    # Mirrors configuration_port.py's _default_alert_filter - the frontend's
    # FilterGroup <-> API mapper always recurses into `conditions`/`groups`
    # unconditionally, so a bare `{}` default crashes it on load.
    return {"id": "root", "operator": "and", "conditions": [], "groups": []}


class ProfilingConfigSchema(BaseModel):
    field_enrichment: dict[str, Any] = Field(
        default_factory=_default_field_enrichment_schema
    )
    strategies: list[ProfilingStrategySchema] = Field(
        default_factory=_default_profiling_strategy_schemas
    )

    @model_validator(mode="after")
    def validate_field_enrichment(self):
        # No recipes yet is the default/untouched state - validate_feature_
        # definition itself requires 1-200 recipes, so skip it rather than
        # reject an admin who hasn't configured enrichment for this segment.
        if self.field_enrichment.get("recipes"):
            from src.domain.models.feature_recipe import validate_feature_definition
            self.field_enrichment = validate_feature_definition(self.field_enrichment)
        return self


class RuleConditionSchema(BaseModel):
    id: str = ""
    variable: str = ""
    comparison: Literal["gt", "gte", "lt", "lte", "eq", "neq", "between", "in"] = "eq"
    values: list[str] = Field(default_factory=list)
    score: float = 0


class DeterministicRuleSchema(RuleConditionSchema):
    decision: Literal["risk_suspected", "risk"] = "risk_suspected"
    aric_action: Literal["soft_block", "hard_block"] = "soft_block"


class AlertParserFieldSchema(BaseModel):
    id: str = ""
    source_field: str = ""
    alias: str = ""
    type: Literal["string", "number", "boolean", "date", "datetime"] = "string"


class AlertParserConfigSchema(BaseModel):
    fields: list[AlertParserFieldSchema] = Field(default_factory=list)


class RubricSchema(BaseModel):
    id: str = ""
    name: str = ""
    conditions: list[RuleConditionSchema] = Field(default_factory=list)


class DeterministicConfigSchema(BaseModel):
    alert_filter: dict[str, Any] = Field(default_factory=_default_alert_filter_schema)
    field_enrichment: dict[str, Any] = Field(default_factory=_default_field_enrichment_schema)
    rules: list[DeterministicRuleSchema] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_field_enrichment(self):
        if self.field_enrichment.get("recipes"):
            from src.domain.models.feature_recipe import validate_feature_definition
            self.field_enrichment = validate_feature_definition(self.field_enrichment)
        return self


class ResearchAgentConfigSchema(BaseModel):
    enabled: bool = False
    max_delegations: int = Field(default=1, ge=1, le=5)
    timeout_seconds: int = Field(default=8, ge=1, le=60)
    max_result_items: int = Field(default=10, ge=1, le=100)


class VectorStoreResearchConfigSchema(ResearchAgentConfigSchema):
    # Interaction budget of the agent <-> vector-store tool calls.
    max_delegations: int = Field(default=3, ge=1, le=10)
    vector_store_instance_id: str | None = None
    similarity_threshold: float = Field(default=0.7, ge=0, le=1)
    max_documents_per_query: int = Field(default=8, ge=1, le=100)
    allowed_asset_types: list[Literal["taxonomy", "modus_operandi", "similar_case", "flag"]] = Field(
        default_factory=lambda: ["taxonomy", "modus_operandi", "similar_case", "flag"]
    )


class HistoryPandasResearchConfigSchema(ResearchAgentConfigSchema):
    max_history_rows: int = Field(default=50, ge=1, le=100_000)
    window_days: int = Field(default=30, ge=0)
    max_analysis_operations: int = Field(default=4, ge=1, le=20)
    allowed_columns: list[str] = Field(default_factory=list)
    allowed_operations: list[Literal[
        "filter", "group_by", "aggregate", "distribution", "trend", "outlier", "comparison"
    ]] = Field(default_factory=lambda: [
        "filter", "group_by", "aggregate", "distribution", "trend", "outlier", "comparison"
    ])


class DelegatedResearchSettingsSchema(BaseModel):
    vector_store: VectorStoreResearchConfigSchema = Field(
        default_factory=VectorStoreResearchConfigSchema
    )
    history_pandas: HistoryPandasResearchConfigSchema = Field(
        default_factory=HistoryPandasResearchConfigSchema
    )

    @model_validator(mode="after")
    def validate_vector_store_selection(self):
        if self.vector_store.enabled and not self.vector_store.vector_store_instance_id:
            raise ValueError(
                "vector_store.vector_store_instance_id is required when delegated vector store research is enabled"
            )
        return self


class AgentToolsConfigSchema(BaseModel):
    watchlist_enabled: bool = False
    watchlist_ids: list[str] = Field(default_factory=list)
    watchlist_compare_field: str | None = None
    calculator_enabled: bool = False
    use_xgboost_model: bool = False
    xgboost_model_id: str | None = None
    xgboost_fraud_threshold: float = 0.8
    xgboost_uncertainty_threshold: float = 0.4
    xgboost_shap_enabled: bool = True
    delegated_research: DelegatedResearchSettingsSchema = Field(
        default_factory=DelegatedResearchSettingsSchema
    )


class ClassificationConfigSchema(AgentToolsConfigSchema):
    prompt: str = ""
    prompt_vars: list[str] = Field(default_factory=list)
    output_labels: list[str] = Field(default_factory=list)
    max_thought_iterations: int = 5


class DetectorConfigSchema(ClassificationConfigSchema):
    pass


class AdversarialConfigSchema(AgentToolsConfigSchema):
    prompt: str = ""
    prompt_vars: list[str] = Field(default_factory=list)
    max_cycles: int = 1
    feed_feedback_to_classification: bool = True


class DetectorAdversarialConfigSchema(AdversarialConfigSchema):
    max_thought_iterations: int = 5


class VoicebotCategoryPromptSchema(BaseModel):
    id: str
    taxonomy_id: str
    prompt: str = ""


class VoicebotConfigSchema(BaseModel):
    base_prompt: str = ""
    base_prompt_vars: list[str] = Field(default_factory=list)
    category_prompts: list[VoicebotCategoryPromptSchema] = Field(
        default_factory=list
    )


class AnalystConfigSchema(BaseModel):
    prompt: str = ""
    prompt_vars: list[str] = Field(default_factory=list)


class DocumentationConfigSchema(BaseModel):
    strategy: DocumentationStrategy = DocumentationStrategy.TEMPLATE
    template: str = ""
    template_vars: list[str] = Field(default_factory=list)
    agent_prompt: str = ""
    agent_prompt_vars: list[str] = Field(default_factory=list)


class PromptFieldSchema(BaseModel):
    prompt: str = ""
    prompt_vars: list[str] = Field(default_factory=list)


class ExecutorConfigSchema(BaseModel):
    aric_marking: PromptFieldSchema = Field(default_factory=PromptFieldSchema)
    voicebot_call: VoicebotConfigSchema = Field(default_factory=VoicebotConfigSchema)
    documentador: DocumentationConfigSchema = Field(
        default_factory=DocumentationConfigSchema
    )
    analyst_escalation: PromptFieldSchema = Field(default_factory=PromptFieldSchema)


class AgentSettingsSchema(BaseModel):
    parser: AlertParserConfigSchema = Field(default_factory=AlertParserConfigSchema)
    deterministic: DeterministicConfigSchema = Field(default_factory=DeterministicConfigSchema)
    profiling: ProfilingConfigSchema = Field(default_factory=ProfilingConfigSchema)
    rubrics: list[RubricSchema] = Field(default_factory=list)
    detector: DetectorConfigSchema = Field(default_factory=DetectorConfigSchema)
    detector_adversarial: DetectorAdversarialConfigSchema = Field(default_factory=DetectorAdversarialConfigSchema)
    classification: ClassificationConfigSchema = Field(
        default_factory=ClassificationConfigSchema
    )
    adversarial: AdversarialConfigSchema = Field(
        default_factory=AdversarialConfigSchema
    )
    analyst: AnalystConfigSchema = Field(default_factory=AnalystConfigSchema)
    executor: ExecutorConfigSchema = Field(default_factory=ExecutorConfigSchema)
    taxonomies: list[TaxonomySchema] = Field(default_factory=list)
    modus_operandi: list[ModusOperandiSchema] = Field(default_factory=list)
    flags: list[FlagSchema] = Field(default_factory=list)
    example_cases: list[ExampleCaseSchema] = Field(default_factory=list)
    active_fields: list[str] = Field(default_factory=list)
    active_model_id: str | None = None


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
    groups: list["FilterGroupSchema"] = Field(default_factory=list)


FilterGroupSchema.model_rebuild()


class SegmentSettingsSchema(BaseModel):
    enabled: bool = False
    filter: FilterGroupSchema = Field(
        default_factory=lambda: FilterGroupSchema(id="root")
    )
    monitoring: MonitoringSettingsSchema = Field(
        default_factory=MonitoringSettingsSchema
    )
    agent: AgentSettingsSchema = Field(default_factory=AgentSettingsSchema)
    order: int = 0


class CreateConfigurationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    # Omit for a brand-new configuration (fresh id, version 1). Set to an
    # existing configuration_id to append a new version to that lineage.
    configuration_id: str | None = None
    # Optimistic-concurrency guard, set alongside configuration_id: the
    # version this draft was loaded from. Rejected with 409 if the lineage
    # has since moved past it.
    based_on_version: int | None = None
    description: str = ""
    general: GeneralSettingsSchema = Field(default_factory=GeneralSettingsSchema)
    infra: InfraSettingsSchema = Field(default_factory=InfraSettingsSchema)
    test: TestSettingsSchema = Field(default_factory=TestSettingsSchema)
    created_by: str | None = Field(default=None, max_length=120)
    segments: dict[str, SegmentSettingsSchema] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_rubrics_sum_to_100(self):
        # Request-side only (not on RubricSchema itself): that schema is
        # also used to serialize stored configurations, and versions saved
        # before this rule must stay readable.
        errors = [
            f"segment {code!r}, rubric {rubric.name or rubric.id!r}: "
            f"condition points sum to {total:g}, must be exactly 100"
            for code, segment in self.segments.items()
            for rubric in segment.agent.rubrics
            if not math.isclose(
                total := sum(condition.score for condition in rubric.conditions), 100
            )
        ]
        if errors:
            raise ValueError("; ".join(errors))
        return self


class ConfigurationChangeResponse(BaseModel):
    path: str
    previous: Any
    proposed: Any


class TestConfigurationResponse(BaseModel):
    valid: bool
    changes: list[ConfigurationChangeResponse]
    warnings: list[str]


class CreateConfigurationDeployRequest(BaseModel):
    target_configuration_id: str = Field(min_length=1)
    target_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)


class ConfigurationDeployRequestResponse(BaseModel):
    id: str
    target_configuration_id: str
    target_version: int
    current_configuration_id: str | None
    current_version: int | None
    title: str
    message: str
    changes: list[ConfigurationChangeResponse]
    requested_by: str
    requested_at: datetime
    status: str
    approved_by: str | None = None
    approved_at: datetime | None = None


class ConfigurationDeployRequestPreviewResponse(BaseModel):
    target_configuration_id: str
    target_version: int
    current_configuration_id: str | None
    current_version: int | None
    changes: list[ConfigurationChangeResponse]


class ConfigurationSummaryResponse(BaseModel):
    configuration_id: str
    version: int
    name: str
    description: str
    active: bool
    # Sticky - true once this version has ever gone to production, even if
    # a later version has since taken over. Frontend uses it to tell
    # whether the next save on this lineage will overwrite this version in
    # place or must mint a new one.
    ever_activated: bool
    ever_tested: bool = False
    created_at: datetime
    updated_at: datetime


class ConfigurationDetailResponse(ConfigurationSummaryResponse):
    general: GeneralSettingsSchema
    infra: InfraSettingsSchema
    test: TestSettingsSchema
    segments: dict[str, SegmentSettingsSchema] = Field(default_factory=dict)
    created_by: str | None = None


# --- Operational settings -------------------------------------------------
# Admin-configured levers that take effect immediately, no version/activate
# lifecycle - see operational_settings_port.py. Reuses AnalystCapacitySchema/
# DayProfileSchema/ShortageBehaviorSchema/TestCleanupPolicy already defined
# above for the versioned configuration schemas.


class AmountTierSchema(BaseModel):
    code: str = Field(..., min_length=1, max_length=60)
    label: str = Field(default="", max_length=120)
    min_inclusive: float = Field(..., ge=0)
    # None = unbounded (the last tier).
    max_exclusive: float | None = None


class OperationalSettingsSchema(BaseModel):
    agent_enabled: bool = True
    analyst_enabled: bool = True
    voicebot_enabled: bool = True
    max_instances: int = 8
    auto_scale: bool = True
    voicebot_max_concurrent_calls: int = Field(default=40, ge=0, le=500)
    analyst_capacity: AnalystCapacitySchema = Field(
        default_factory=AnalystCapacitySchema
    )
    queue_max_lifetime_value: int = 60
    queue_max_lifetime_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    queue_discard_amount_threshold: float = 0
    queue_rule_filter_enabled: bool = False
    queue_rule_filter_mode: ListMembershipMode = ListMembershipMode.BELONGS
    queue_allowed_triggered_rules: list[str] = Field(default_factory=list)
    queue_discard_behavior: ShortageBehaviorSchema = Field(
        default_factory=ShortageBehaviorSchema
    )
    max_test_instances: int = 4
    max_concurrent_experiments: int = 3
    experiment_timeout_minutes: int = 30
    max_stored_test_runs: int = 20
    test_cleanup_policy: TestCleanupPolicy = TestCleanupPolicy.OLDEST
    # Request: omitted/None keeps the current tiers; [] clears them. Must be
    # contiguous, non-overlapping and cover 0 -> inf (else 422). Response:
    # always the full current list.
    amount_tiers: list[AmountTierSchema] | None = None
    # Read-only: bumped server-side on every amount_tiers change, ignored
    # on requests.
    amount_tier_set_version: int = 0
    # Share (0..1) of finished alerts sent to the reasoning LLM-judge;
    # 0 disables it.
    reasoning_evaluation_sample_rate: float = Field(default=0.05, ge=0, le=1)


class UpdateOperationalSettingsRequest(BaseModel):
    settings: OperationalSettingsSchema
    # Free-text identifier captured for traceability only - not an enforced
    # identity, this codebase has no auth/permission system wired anywhere.
    changed_by: str | None = Field(default=None, max_length=120)


class SettingChangeResponse(BaseModel):
    path: str
    previous: Any
    new: Any


class OperationalSettingsChangeResponse(BaseModel):
    id: str
    changed_by: str | None
    changed_at: datetime
    changes: list[SettingChangeResponse]


# --- Tag catalog ---------------------------------------------------------


class TagEntrySchema(BaseModel):
    id: str
    category: TagCategory
    value: str
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateTagRequest(BaseModel):
    category: TagCategory
    value: str = Field(..., min_length=1, max_length=200)


class UpdateTagRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None


# --- Marcación catalog -----------------------------------------------------


class MarcacionCategorySchema(BaseModel):
    id: str
    value: str
    risk_label: RiskLabel
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateMarcacionCategoryRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    risk_label: RiskLabel


class UpdateMarcacionCategoryRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=200)
    risk_label: RiskLabel | None = None
    active: bool | None = None


# --- Knowledge library (global, config-independent reference data used to
# populate a segment's taxonomies/modus operandi/flags/similar cases via
# "Importar de biblioteca" - snapshot-copied, never referenced live) ------


class TaxonomyLibraryEntrySchema(BaseModel):
    id: str
    code: str
    name: str
    description: str
    variables: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateTaxonomyLibraryEntryRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    variables: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class UpdateTaxonomyLibraryEntryRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    variables: list[str] | None = None
    examples: list[str] | None = None
    active: bool | None = None


# --- Channel library (global, config-independent - replaces the old fixed
# SegmentCode enum; a configuration's segments dict keys off these ids) ---


class ChannelLibraryEntrySchema(BaseModel):
    id: str
    code: str
    name: str
    description: str
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateChannelLibraryEntryRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class UpdateChannelLibraryEntryRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    active: bool | None = None


class ModusOperandiPlaybookSchema(BaseModel):
    strategy: str = Field(default="", max_length=4000)
    resolution: ShortageBehaviorSchema = Field(
        default_factory=lambda: ShortageBehaviorSchema(
            resolution_tag=ResolutionTag.SCALE_TO_ANALYST
        )
    )
    if_no_voicebot: ShortageBehaviorSchema = Field(
        default_factory=ShortageBehaviorSchema
    )
    if_no_analyst: ShortageBehaviorSchema = Field(
        default_factory=ShortageBehaviorSchema
    )


class ModusOperandiLibraryEntrySchema(BaseModel):
    id: str
    title: str
    narrative: str
    taxonomy_library_id: str
    evolved_variables: list[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime
    playbook: ModusOperandiPlaybookSchema | None = None


class CreateModusOperandiLibraryEntryRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    narrative: str = Field(..., min_length=1, max_length=2000)
    taxonomy_library_id: str
    evolved_variables: list[str] = Field(default_factory=list)


class UpdateModusOperandiLibraryEntryRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    narrative: str | None = Field(default=None, min_length=1, max_length=2000)
    taxonomy_library_id: str | None = None
    evolved_variables: list[str] | None = None
    active: bool | None = None
    playbook: ModusOperandiPlaybookSchema | None = None


class FlagLibraryEntrySchema(BaseModel):
    id: str
    flag_type: FlagType
    name: str
    description: str
    evolved_variables: list[str] = Field(default_factory=list)
    modus_operandi_library_ids: list[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateFlagLibraryEntryRequest(BaseModel):
    flag_type: FlagType
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    evolved_variables: list[str] = Field(default_factory=list)
    modus_operandi_library_ids: list[str] = Field(default_factory=list)


class UpdateFlagLibraryEntryRequest(BaseModel):
    flag_type: FlagType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    evolved_variables: list[str] | None = None
    modus_operandi_library_ids: list[str] | None = None
    active: bool | None = None


class SimilarCaseLibraryEntrySchema(BaseModel):
    id: str
    text: str
    modus_operandi_library_id: str
    taxonomy_library_id: str
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateSimilarCaseLibraryEntryRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    modus_operandi_library_id: str
    taxonomy_library_id: str


class UpdateSimilarCaseLibraryEntryRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    modus_operandi_library_id: str | None = None
    taxonomy_library_id: str | None = None
    active: bool | None = None


# --- Vector-store instances -------------------------------------------------


class VectorStoreInstanceSchema(BaseModel):
    id: str
    version: int
    name: str
    description: str
    created_at: datetime
    created_by: str
    updated_at: datetime | None
    updated_by: str | None
    promoted_version: int | None = None
    promoted_at: datetime | None = None
    promoted_by: str | None = None


class CreateVectorStoreInstanceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class UpdateVectorStoreInstanceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class VectorStoreDocumentSchema(BaseModel):
    relation_id: str
    asset_type: KnowledgeAssetType
    asset_id: str
    asset_version: int


class AddVectorStoreDocumentRequest(BaseModel):
    asset_type: KnowledgeAssetType
    asset_id: str = Field(..., min_length=1)
    # The asset version is explicit so a later edit can add a new immutable
    # revision alongside the original relation.
    asset_version: int = Field(default=1, ge=1)


# --- Resolution method catalog ------------------------------------------


class ResolutionMethodSchema(BaseModel):
    id: str
    value: str
    resolution_tag: ResolutionTag
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateResolutionMethodRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    resolution_tag: ResolutionTag


class UpdateResolutionMethodRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=200)
    resolution_tag: ResolutionTag | None = None
    active: bool | None = None


# --- Variable catalog --------------------------------------------------


class VariableSchema(BaseModel):
    id: str
    value: str
    description: str
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateVariableRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)


class UpdateVariableRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None


# --- Watchlists (blacklist / whitelist) ------------------------------------


class WatchlistSchema(BaseModel):
    id: str
    name: str
    description: str
    list_type: WatchlistType
    element_count: int
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateWatchlistRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=1000)
    list_type: WatchlistType
    # Small inline seed list only - bulk loads go through the
    # /elements/import file upload endpoint instead of one giant JSON body.
    elements: list[str] = Field(default_factory=list)


class UpdateWatchlistRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    active: bool | None = None


class WatchlistElementsPageSchema(BaseModel):
    values: list[str]
    next_cursor: str | None = None


class AddWatchlistElementsRequest(BaseModel):
    values: list[str] = Field(..., min_length=1)


class AddWatchlistElementsResponse(BaseModel):
    added: int


class RemoveWatchlistElementsRequest(BaseModel):
    values: list[str] = Field(..., min_length=1)


class RemoveWatchlistElementsResponse(BaseModel):
    removed: int


class CheckWatchlistMembershipRequest(BaseModel):
    list_type: WatchlistType
    value: str = Field(..., min_length=1)


class WatchlistMatchSchema(BaseModel):
    watchlist_id: str
    watchlist_name: str


class CheckWatchlistMembershipResponse(BaseModel):
    is_member: bool
    matches: list[WatchlistMatchSchema]


# --- Event simulation (scenarios) -------------------------------------------


class RateIntervalSchema(BaseModel):
    start_offset_seconds: int = Field(..., ge=0)
    end_offset_seconds: int = Field(..., gt=0)
    events_per_minute: float = Field(..., ge=0)


class FieldGeneratorSchema(BaseModel):
    kind: GeneratorKind
    value: Any = None
    weights: dict[str, float] | None = None
    params: dict[str, float] | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    model: str | None = None
    temperature: float = 0.0
    seed_dataset_name: str | None = None
    seed_field: str | None = None


class CreateSimulationScenarioRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    output_mode: OutputMode
    rate_schedule: list[RateIntervalSchema] = Field(..., min_length=1)
    field_specs: dict[str, FieldGeneratorSchema] = Field(..., min_length=1)
    target_dataset_name: str | None = None
    created_by: str | None = None


class UpdateSimulationScenarioRequest(BaseModel):
    name: str | None = None
    rate_schedule: list[RateIntervalSchema] | None = None
    field_specs: dict[str, FieldGeneratorSchema] | None = None
    target_dataset_name: str | None = None


class SimulationScenarioResponse(BaseModel):
    id: UUID
    name: str
    status: ScenarioStatus
    output_mode: OutputMode
    rate_schedule: list[RateIntervalSchema]
    field_specs: dict[str, FieldGeneratorSchema]
    target_dataset_name: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    events_emitted: int
    last_tick_offset_seconds: int
    error: str | None


class SimulationStatusResponse(BaseModel):
    scenario_id: UUID
    status: ScenarioStatus
    events_emitted: int
    last_tick_offset_seconds: int
    error: str | None


# --- Operations: live capacity, analyst queue, voicebot callback ---------


class ChannelCapacitySchema(BaseModel):
    available: int
    status: str
    total: int | None = None


class OperationsCapacityResponse(BaseModel):
    analysts: ChannelCapacitySchema
    voicebot: ChannelCapacitySchema
    bidi: ChannelCapacitySchema
    updated_at: datetime


class ResourceReservationResponse(BaseModel):
    id: str
    resource: str
    alert_id: str
    holder: str
    # Display name of the analyst holding it (None for a voicebot call or
    # an unknown user).
    holder_name: str | None = None
    reserved_at: datetime
    expires_at: datetime
    status: str
    released_at: datetime | None = None
    release_reason: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class AnalystQueueAlertResponse(BaseModel):
    alert_id: UUID
    event_id: str
    event_type: str
    status: str
    customer_id: str | None
    created_at: datetime
    payload: dict[str, Any]
    reservation: ResourceReservationResponse | None = None


class AlertStepResponse(BaseModel):
    step_name: str
    status: str
    attempt: int
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AlertDetailResponse(AnalystQueueAlertResponse):
    workflow_execution_id: UUID | None = None
    workflow_status: str | None = None
    workflow_output: dict[str, Any] | None = None
    steps: list[AlertStepResponse] = Field(default_factory=list)


class ResolveEscalatedAlertRequest(BaseModel):
    decision: Literal["block", "pass", "bidi"]
    notes: str = Field(default="", max_length=4000)


class VoicebotCallbackRequest(BaseModel):
    alert_id: UUID
    # Provider-defined result of the call (e.g. "confirmed_by_customer",
    # "fraud_reported", "no_answer") - stored as-is on the reservation.
    outcome: str = Field(..., min_length=1, max_length=120)
    detail: dict[str, Any] = Field(default_factory=dict)


# --- Metrics (A2): GET /metrics/overview, GET /metrics/agent ----------------
# Mirrors application/dtos/metrics_dtos.py. Every number is a sum of additive
# rollup measures; rates/averages are numerator / denominator on the client.


class MetricsRangeSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime = Field(alias="from")
    to: datetime
    timezone: str
    amount_tier_set_versions: list[str] = Field(default_factory=list)


class MetricsPeriodSchema(BaseModel):
    level: Literal["day", "month", "year"]
    period: str
    period_start: date
    period_end: date
    hours: list[int]
    partial: bool
    maturation: Literal["maturing", "may_vary", "stable"]
    alerts: int
    amount_sum: float
    decided: int
    false_positives: int
    undetected_fraud: int
    reviewed: int


class MetricsWarningSchema(BaseModel):
    code: Literal["partial_period", "amount_tier_set_changed", "fraud_label_maturing"]
    message: str
    periods: list[str] = Field(default_factory=list)


class HistogramBucketSchema(BaseModel):
    bucket: str
    upper_bound_seconds: float | None
    count: int


class ResolutionTimeStatsSchema(BaseModel):
    count: int
    sum_seconds: float
    within_sla_count: int
    histogram: list[HistogramBucketSchema]


class FraudQualityStatsSchema(BaseModel):
    decided: int
    pending: int
    true_positives: int
    true_negatives: int
    false_positives: int
    undetected_fraud: int
    true_positive_amount_sum: float
    false_positive_amount_sum: float
    undetected_fraud_amount_sum: float
    reviewed: int
    reviewed_changed: int
    reviewed_confirmed: int
    review_events: int
    maturation_histogram: list[HistogramBucketSchema]


class DimensionBucketSchema(BaseModel):
    value: str
    alerts: int
    amount_sum: float
    amount_count: int
    decided: int
    false_positives: int
    undetected_fraud: int


class HourlyProfileSlotSchema(BaseModel):
    hour: int
    alerts: int
    amount_sum: float
    resolution_time_count: int
    resolution_time_sum_seconds: float
    within_sla_count: int


class MetricsTotalsSchema(BaseModel):
    alerts: int
    amount_sum: float
    amount_count: int


class MetricsOverviewResponse(BaseModel):
    range: MetricsRangeSchema
    periods: list[MetricsPeriodSchema]
    warnings: list[MetricsWarningSchema]
    totals: MetricsTotalsSchema
    funnel_by_status: list[DimensionBucketSchema]
    fraud_quality: FraudQualityStatsSchema
    resolution_time: ResolutionTimeStatsSchema
    distributions: dict[str, list[DimensionBucketSchema]]
    hourly_profile: list[HourlyProfileSlotSchema]


class ResolutionMethodStatsSchema(BaseModel):
    resolution_method: Literal["aria", "analyst", "voicebot", "bidi", "unknown"]
    alerts: int
    fraud_marks: int
    no_fraud_marks: int
    fraud_quality: FraudQualityStatsSchema
    resolution_time: ResolutionTimeStatsSchema


class RecommendationAcceptanceSchema(BaseModel):
    available: bool
    accepted: int | None
    ignored: int | None
    reason: str


class AgentMetricsResponse(BaseModel):
    range: MetricsRangeSchema
    periods: list[MetricsPeriodSchema]
    warnings: list[MetricsWarningSchema]
    totals: MetricsTotalsSchema
    by_resolution_method: list[ResolutionMethodStatsSchema]
    fraud_quality: FraudQualityStatsSchema
    resolution_time: ResolutionTimeStatsSchema
    hourly_profile: list[HourlyProfileSlotSchema]
    recommendations: RecommendationAcceptanceSchema


# --- Metrics (A2): GET /metrics/technical ----------------------------------
# Mirrors application/dtos/technical_metrics_dtos.py. Sums only: avg
# latency = duration.sum_seconds / duration.count, hallucination % =
# evaluations.hallucinations / evaluations.evaluated, etc.


class DurationStatsSchema(BaseModel):
    count: int
    sum_seconds: float
    histogram: list[HistogramBucketSchema]


class WorkflowStepStatsSchema(BaseModel):
    step_name: str
    executions: int
    succeeded: int
    failed: int
    retries: int
    duration: DurationStatsSchema


class LLMCallStatsSchema(BaseModel):
    model: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    latency: DurationStatsSchema


class ResearchCallStatsSchema(BaseModel):
    source: str
    calls: int
    ok: int
    failed: int
    timeout: int


class EvaluationStatsSchema(BaseModel):
    evaluated: int
    hallucinations: int
    data_use_correct: int
    invalid: int


class TechnicalHourSlotSchema(BaseModel):
    hour: int
    step_executions: int
    step_failed: int
    step_duration_sum_seconds: float
    step_duration_count: int
    llm_calls: int
    llm_errors: int
    input_tokens: int
    output_tokens: int
    research_calls: int
    research_failed: int
    research_timeout: int


class TechnicalPeriodSchema(BaseModel):
    level: Literal["day", "month", "year"]
    period: str
    period_start: date
    period_end: date
    hours: list[int]
    partial: bool
    maturation: Literal["maturing", "may_vary", "stable"]
    step_executions: int
    step_failed: int
    llm_calls: int
    llm_errors: int
    input_tokens: int
    output_tokens: int
    research_calls: int
    evaluated: int
    hallucinations: int
    data_use_correct: int


class TechnicalMetricsResponse(BaseModel):
    range: MetricsRangeSchema
    periods: list[TechnicalPeriodSchema]
    warnings: list[MetricsWarningSchema]
    workflow_steps: WorkflowStepStatsSchema
    workflow_steps_by_step: list[WorkflowStepStatsSchema]
    llm_calls: LLMCallStatsSchema
    llm_calls_by_model: list[LLMCallStatsSchema]
    research_calls: ResearchCallStatsSchema
    research_calls_by_source: list[ResearchCallStatsSchema]
    evaluations: EvaluationStatsSchema
    hourly_profile: list[TechnicalHourSlotSchema]


# --- Fraud history (A3) + fraud_label review (C5) ----------------------------


class AlertHistoryItemSchema(BaseModel):
    alert_id: UUID
    event_id: str
    event_type: str
    # Live alert status (the metrics "status" filter matches the snapshot's).
    status: str
    customer_id: str | None
    created_at: datetime
    updated_at: datetime
    # False = no metrics event touched this alert yet; the fields below are
    # then derived from its payload (mark/fraud_label "pending").
    has_snapshot: bool
    origin: str | None
    segment: str | None
    channel: str | None
    subchannel: str | None
    amount: float | None
    amount_tier: str
    amount_tier_set_version: int | None
    configuration_id: str | None
    resolution_method: Literal["aria", "analyst", "voicebot", "bidi"] | None
    mark: Literal["fraud", "no_fraud", "pending"]
    fraud_label: Literal["fraud", "no_fraud", "pending"]
    marked_at: datetime | None
    fraud_reviewed_at: datetime | None
    fraud_review_count: int
    resolution_time_seconds: float | None


class AlertHistoryPageResponse(BaseModel):
    items: list[AlertHistoryItemSchema]
    # Opaque - pass back as ?cursor= for the next page; null = no more.
    next_cursor: str | None


class FraudReviewRequest(BaseModel):
    fraud_label: Literal["fraud", "no_fraud"]
    note: str = Field(default="", max_length=2000)


class FraudLabelReviewSchema(BaseModel):
    id: UUID
    alert_id: UUID
    from_label: Literal["fraud", "no_fraud", "pending"]
    to_label: Literal["fraud", "no_fraud"]
    reviewed_by: str
    reviewed_at: datetime
    channel: Literal["ui", "csv"]
    note: str


class FraudReviewResponse(BaseModel):
    review: FraudLabelReviewSchema
    # The alert's snapshot after the review.
    mark: Literal["fraud", "no_fraud", "pending"]
    fraud_label: Literal["fraud", "no_fraud", "pending"]
    marked_at: datetime | None
    fraud_reviewed_at: datetime | None
    fraud_review_count: int


class FraudLabelReviewRowResultSchema(BaseModel):
    row: int
    alert_id: str
    fraud_label: str
    status: Literal["applied", "invalid", "not_found", "error"]
    error: str | None = None


class UploadFraudLabelReviewImportResponse(BaseModel):
    task_id: str
    status: Literal["PENDING", "READY", "FAILED"]


class FraudLabelReviewImportResponse(BaseModel):
    task_id: str
    status: Literal["PENDING", "READY", "FAILED"]
    total: int
    applied: int
    failed: int
    rows: list[FraudLabelReviewRowResultSchema]
    error: str | None = None


class LiveAlertFunnelResponse(BaseModel):
    received: int
    processing: int
    escalated: int
    voicebot_in_call: int
    measured_at: datetime
