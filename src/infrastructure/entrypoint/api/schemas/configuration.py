from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from src.application.ports.configuration_port import (
    DocumentationStrategy,
    FilterConditionOperator,
    FlagType,
    LogicalOperator,
    ProfilingPromptMode,
    ProfilingStrategyKey,
    ResolutionTag,
    SamplingIntervalUnit,
    TestCleanupPolicy,
)
from src.application.ports.tag_catalog_port import TagCategory

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


class RubricSchema(BaseModel):
    id: str = ""
    name: str = ""
    conditions: list[RuleConditionSchema] = Field(default_factory=list)


class DeterministicConfigSchema(BaseModel):
    alert_filter: dict[str, Any] = Field(default_factory=_default_alert_filter_schema)
    field_enrichment: dict[str, Any] = Field(
        default_factory=_default_field_enrichment_schema
    )
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
    allowed_asset_types: list[
        Literal["taxonomy", "modus_operandi", "similar_case", "flag"]
    ] = Field(
        default_factory=lambda: ["taxonomy", "modus_operandi", "similar_case", "flag"]
    )


class HistoryPandasResearchConfigSchema(ResearchAgentConfigSchema):
    max_history_rows: int = Field(default=50, ge=1, le=100_000)
    window_days: int = Field(default=30, ge=0)
    max_analysis_operations: int = Field(default=4, ge=1, le=20)
    allowed_columns: list[str] = Field(default_factory=list)
    allowed_operations: list[
        Literal[
            "filter",
            "group_by",
            "aggregate",
            "distribution",
            "trend",
            "outlier",
            "comparison",
        ]
    ] = Field(
        default_factory=lambda: [
            "filter",
            "group_by",
            "aggregate",
            "distribution",
            "trend",
            "outlier",
            "comparison",
        ]
    )


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
    category_prompts: list[VoicebotCategoryPromptSchema] = Field(default_factory=list)


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
    deterministic: DeterministicConfigSchema = Field(
        default_factory=DeterministicConfigSchema
    )
    profiling: ProfilingConfigSchema = Field(default_factory=ProfilingConfigSchema)
    rubrics: list[RubricSchema] = Field(default_factory=list)
    detector: DetectorConfigSchema = Field(default_factory=DetectorConfigSchema)
    detector_adversarial: DetectorAdversarialConfigSchema = Field(
        default_factory=DetectorAdversarialConfigSchema
    )
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
    groups: list[FilterGroupSchema] = Field(default_factory=list)


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
