from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from src.domain.configurations.entities import (
    DocumentationStrategy,
    ProfilingPromptMode,
    ProfilingStrategyKey,
)
from src.infrastructure.entrypoint.api.schemas.configuration_catalog import (
    ExampleCaseSchema,
    FlagSchema,
    ModusOperandiSchema,
    TaxonomySchema,
)


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
    return {
        "schema_version": 2,
        "mappings": {"timezone": "America/Bogota", "history": "history"},
        "recipes": [],
    }


class ProfilingConfigSchema(BaseModel):
    field_enrichment: dict[str, Any] = Field(default_factory=_default_field_enrichment_schema)
    strategies: list[ProfilingStrategySchema] = Field(default_factory=_default_profiling_strategy_schemas)

    @model_validator(mode="after")
    def validate_field_enrichment(self):
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


def _default_alert_filter_schema() -> dict[str, Any]:
    return {"id": "root", "operator": "and", "conditions": [], "groups": []}


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
    planner: Literal["llm", "heuristic"] = "llm"
    allowed_columns: list[str] = Field(default_factory=list)
    allowed_operations: list[Literal["filter", "group_by", "aggregate", "distribution", "trend", "outlier", "comparison"]] = Field(
        default_factory=lambda: ["filter", "group_by", "aggregate", "distribution", "trend", "outlier", "comparison"]
    )


class DelegatedResearchSettingsSchema(BaseModel):
    vector_store: VectorStoreResearchConfigSchema = Field(default_factory=VectorStoreResearchConfigSchema)
    history_pandas: HistoryPandasResearchConfigSchema = Field(default_factory=HistoryPandasResearchConfigSchema)

    @model_validator(mode="after")
    def validate_vector_store_selection(self):
        if self.vector_store.enabled and not self.vector_store.vector_store_instance_id:
            raise ValueError("vector_store.vector_store_instance_id is required when delegated vector store research is enabled")
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
    delegated_research: DelegatedResearchSettingsSchema = Field(default_factory=DelegatedResearchSettingsSchema)


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
    documentador: DocumentationConfigSchema = Field(default_factory=DocumentationConfigSchema)
    analyst_escalation: PromptFieldSchema = Field(default_factory=PromptFieldSchema)


class AgentSettingsSchema(BaseModel):
    deterministic: DeterministicConfigSchema = Field(default_factory=DeterministicConfigSchema)
    profiling: ProfilingConfigSchema = Field(default_factory=ProfilingConfigSchema)
    rubrics: list[RubricSchema] = Field(default_factory=list)
    detector: DetectorConfigSchema = Field(default_factory=DetectorConfigSchema)
    detector_adversarial: DetectorAdversarialConfigSchema = Field(default_factory=DetectorAdversarialConfigSchema)
    classification: ClassificationConfigSchema = Field(default_factory=ClassificationConfigSchema)
    adversarial: AdversarialConfigSchema = Field(default_factory=AdversarialConfigSchema)
    analyst: AnalystConfigSchema = Field(default_factory=AnalystConfigSchema)
    executor: ExecutorConfigSchema = Field(default_factory=ExecutorConfigSchema)
    taxonomies: list[TaxonomySchema] = Field(default_factory=list)
    modus_operandi: list[ModusOperandiSchema] = Field(default_factory=list)
    flags: list[FlagSchema] = Field(default_factory=list)
    example_cases: list[ExampleCaseSchema] = Field(default_factory=list)
    active_fields: list[str] = Field(default_factory=list)
    active_model_id: str | None = None
