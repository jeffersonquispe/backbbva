from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SamplingIntervalUnit(StrEnum):
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


class TestCleanupPolicy(StrEnum):
    MANUAL = "manual"
    OLDEST = "oldest"
    FAILED_FIRST = "failed-first"


class ListMembershipMode(StrEnum):
    BELONGS = "belongs"
    NOT_BELONGS = "not_belongs"


class TagCategory(StrEnum):
    INTEGRATION_POINT = "integration_point"
    TRIGGERED_RULE = "triggered_rule"
    EVENT_TYPE = "event_type"


class ResolutionTag(StrEnum):
    # Fixed dimension a ResolutionMethod catalog entry maps onto (see
    # resolution_method_catalog_port.py). The executor branches on it when
    # it applies a modus operandi playbook's fallback chain (see
    # ModusOperandiPlaybook in domain/fraud_knowledge/library_entities.py).
    SCALE_TO_ANALYST = "scale_to_analyst"
    SEND_TO_VOICEBOT = "send_to_voicebot"
    HANDLE_BY_ARIA = "handle_by_aria"
    BLOCK_SOFT = "block_soft"
    BLOCK_HARD = "block_hard"


@dataclass
class Taxonomy:
    id: str
    code: str
    name: str
    description: str
    variables: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    active: bool = True
    segmento: str = ""


@dataclass
class ModusOperandi:
    # Belongs to (and is owned by) exactly one taxonomy.
    id: str
    title: str
    narrative: str
    taxonomy_id: str
    evolved_variables: list[str] = field(default_factory=list)
    active: bool = True
    segmento: str = ""


class FlagType(StrEnum):
    RED = "red"
    YELLOW = "yellow"


@dataclass
class Flag:
    # Many-to-many with ModusOperandi (a flag can evidence multiple modus
    # operandi, and vice versa) - no taxonomy_id here, since with M2M a
    # flag's taxonomy is derived from whichever modus operandi it's
    # attached to, not a single denormalized value.
    id: str
    flag_type: FlagType
    name: str
    description: str
    evolved_variables: list[str] = field(default_factory=list)
    modus_operandi_ids: list[str] = field(default_factory=list)
    segmento: str = ""


@dataclass
class ExampleCase:
    # Belongs to both a modus operandi and (denormalized) its taxonomy at
    # once - mirrors SimilarCaseDocument in fraud_knowledge_port.py.
    id: str
    text: str
    modus_operandi_id: str
    taxonomy_id: str
    segmento: str = ""


@dataclass
class DistributionValue:
    id: str
    label: str
    pct: int


@dataclass
class SamplingCriterion:
    id: str
    name: str
    values: list[DistributionValue] = field(default_factory=list)


@dataclass
class DayProfile:
    id: str
    name: str
    description: str
    hourly: list[int] = field(default_factory=lambda: [0] * 24)


def _default_analyst_profiles() -> list[DayProfile]:
    return [
        DayProfile(
            id="regular",
            name="Día regular",
            description="Cobertura estándar para días hábiles sin eventos especiales.",
            hourly=[4] * 24,
        ),
        DayProfile(
            id="pago",
            name="Día de pago",
            description="Refuerzo por mayor volumen de alertas en fechas de pago.",
            hourly=[8] * 24,
        ),
    ]


@dataclass
class AnalystCapacity:
    profiles: list[DayProfile] = field(default_factory=_default_analyst_profiles)
    default_profile_id: str = "regular"
    day_overrides: dict[int, str] = field(
        default_factory=lambda: {15: "pago", 20: "pago", 30: "pago"}
    )


@dataclass
class ShortageBehavior:
    # One pick from the resolution-method catalog
    # (ResolutionMethodCatalogRepository). resolution_tag stays denormalized
    # (the catalog entry's mapped tag, copied at save time) so readers can
    # branch on it without a catalog lookup; resolution_method_id is
    # nullable so a fresh default (block_soft) is valid before an admin
    # picks a method. Used by OperationalSettings.queue_discard_behavior
    # and by a modus operandi playbook's primary method + fallbacks.
    resolution_tag: ResolutionTag = ResolutionTag.BLOCK_SOFT
    resolution_method_id: str | None = None


@dataclass
class GeneralSettings:
    # Agent/analyst/voicebot on-off switches are NOT here: they take effect
    # immediately, so they live in the OperationalSettings singleton
    # (operational_settings_port.py), never in a versioned configuration.
    migration_window_enabled: bool = False
    # ISO datetime string ("YYYY-MM-DDTHH:MM"), same format the frontend's
    # <input type="datetime-local"> produces - stored as-is, no parsing.
    migration_window_datetime: str = "2000-01-01T02:00"


@dataclass
class InfraSettings:
    max_instances: int = 8
    auto_scale: bool = True
    # Eviction schedule for the fraud-history record: it lives in the active
    # database for `fraud_history_db_retention_days`, then moves to cold
    # storage, where it survives another `fraud_history_cold_storage_retention_months`
    # before being purged for good.
    fraud_history_db_retention_days: int = 90
    fraud_history_cold_storage_retention_months: int = 24


@dataclass
class MonitoringSettings:
    sampling_interval_value: int = 30
    sampling_interval_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    sampling_criteria: list[SamplingCriterion] = field(default_factory=list)
    max_samples: int = 200
    prompt_clasificacion: str = ""
    prompt_clasificacion_vars: list[str] = field(default_factory=list)
    prompt_analista: str = ""
    prompt_analista_vars: list[str] = field(default_factory=list)
    prompt_monitoreo: str = ""
    prompt_monitoreo_vars: list[str] = field(default_factory=list)


def _default_field_enrichment() -> dict[str, Any]:
    # Same shape as models' FeatureConfiguration (schema_version/mappings/
    # recipes - see src/domain/models/feature_recipe.py, validated by the
    # same validate_feature_definition). Unlike models, where the dataset's
    # history column varies per source, this context always exposes a
    # single alert's transaction history under a fixed "history" key (see
    # EnrichProfilingFieldsUseCase), so the default mapping pre-fills it -
    # an admin building a profiling recipe never has to pick a history path.
    return {
        "schema_version": 2,
        "mappings": {"timezone": "America/Bogota", "history": "history"},
        "recipes": [],
    }


class ProfilingStrategyKey(StrEnum):
    USUARIO = "usuario"
    TRANSACCION = "transaccion"
    TRANSACCIONAL = "transaccional"


# Whether main_prompt is used as a literal f-string (placeholders
# substituted directly, no LLM call) or as an actual prompt sent to an LLM.
# categorization_prompt has no such switch - it is always LLM-executed.
class ProfilingPromptMode(StrEnum):
    FSTRING = "fstring"
    LLM = "llm"


@dataclass
class ProfilingStrategy:
    key: ProfilingStrategyKey
    main_prompt: str = ""
    main_prompt_vars: list[str] = field(default_factory=list)
    main_prompt_mode: ProfilingPromptMode = ProfilingPromptMode.FSTRING
    # Sub-prompt always run through an LLM to categorize/quantize values.
    categorization_prompt: str = ""
    categorization_prompt_vars: list[str] = field(default_factory=list)
    use_pandas_history_mcp: bool = False


def _default_profiling_strategies() -> list[ProfilingStrategy]:
    return [ProfilingStrategy(key=key) for key in ProfilingStrategyKey]


@dataclass
class ProfilingConfig:
    # Feature-recipe configuration (dict, validated by
    # validate_feature_definition - see src/domain/models/feature_recipe.py)
    # producing named enrichment variables. Each enabled recipe's `name` is
    # available to Perfilamiento's prompts (see
    # EnrichProfilingFieldsUseCase/_run_profiling in
    # alert_review_workflow.py) - not yet to the other agent prompts
    # (classification/adversarial/analyst), which don't resolve {variable}
    # tokens at all today.
    field_enrichment: dict[str, Any] = field(default_factory=_default_field_enrichment)
    # Fixed 3-step chain (usuario -> transaccion -> transaccional), run in
    # this order - variable availability no longer depends on that order.
    strategies: list[ProfilingStrategy] = field(
        default_factory=_default_profiling_strategies
    )


# Deterministic scoring is configuration data. Execution is deliberately
# owned by the alert workflow, so these structures remain framework-neutral.
@dataclass
class RuleCondition:
    id: str = ""
    variable: str = ""
    comparison: str = "eq"
    values: list[str] = field(default_factory=list)
    score: float = 0


@dataclass
class DeterministicRule(RuleCondition):
    decision: str = "risk_suspected"
    aric_action: str = "soft_block"


@dataclass
class Rubric:
    id: str = ""
    name: str = ""
    conditions: list[RuleCondition] = field(default_factory=list)


def _default_alert_filter() -> dict[str, Any]:
    # Same serialized shape as an empty FilterGroup(id="root") (see below) -
    # the frontend always runs this through its FilterGroup <-> API mapper,
    # which recurses into `conditions`/`groups` unconditionally, so a bare
    # `{}` default crashes it on load. Kept as a plain dict here (not a real
    # FilterGroup) only because AgentSettings is declared before FilterGroup
    # in this file, and it stays unevaluated by the workflow either way.
    return {"id": "root", "operator": "and", "conditions": [], "groups": []}


@dataclass
class DeterministicConfig:
    # Kept as the same serialized FilterGroup shape used by segment routing.
    # It is a dict here because AgentSettings is declared before FilterGroup.
    alert_filter: dict[str, Any] = field(default_factory=_default_alert_filter)
    field_enrichment: dict[str, Any] = field(default_factory=_default_field_enrichment)
    rules: list[DeterministicRule] = field(default_factory=list)


# Both ClassificationConfig and AdversarialConfig share this same
# tool-picker shape (item 1/2/3 of the "reemplaza base de conocimiento
# vector store" request): a plain enable switch per tool family, replacing
# the old fixed VectorStoreTool/BuiltInTool category enums. Vector-store
# search is now scoped to specific vector_store_instance_port.py instances
# (picked by id, not by document-type category) and blacklist/whitelist are
# now their own switch (watchlist_port.py instances, picked by id) instead
# of being lumped into "built-in tools" alongside the calculator - which is
# now just its own switch, nothing else was ever a built-in tool worth
# grouping. Membership direction (watch for presence vs. absence) isn't
# stored here - it's intrinsic to each Watchlist's own list_type (see
# ListMembershipMode / watchlist_port.py), read off the watchlist itself.


@dataclass
class ResearchAgentConfig:
    """Execution budget shared by delegated evidence-gathering agents."""

    enabled: bool = False
    max_delegations: int = 1
    # Per call (each vector-store interaction / each history round); an
    # overrun comes back FAILED and the step carries on without it.
    timeout_seconds: int = 8
    max_result_items: int = 10


@dataclass
class VectorStoreResearchConfig(ResearchAgentConfig):
    # Called by the agent itself as a tool (search_vector_store),
    # as many times as it needs: max_delegations is the interaction budget
    # per step. The only vector-store path - it replaced the old direct
    # get_similar_* tools ("Base de conocimiento").
    max_delegations: int = 3
    vector_store_instance_id: str | None = None
    # The exact OpenSearch generation this version searches (see
    # vector_store_generations.py). Filled in when the version is saved, so
    # a test and the deploy request that follows it use the same documents.
    vector_store_generation: int | None = None
    similarity_threshold: float = 0.7
    max_documents_per_query: int = 8
    allowed_asset_types: list[str] = field(
        default_factory=lambda: ["taxonomy", "modus_operandi", "similar_case", "flag"]
    )


@dataclass
class HistoryPandasResearchConfig(ResearchAgentConfig):
    # Runs when the step stays inconclusive (Detector/Clasificación) or the
    # adversarial challenges the result, up to max_delegations rounds
    # (capped at 5): analysis, then the step again with its findings, while
    # the step stays open and each round brings new findings. The selector below scopes the
    # history it analyzes: allowed_columns (empty = all), window_days
    # before the alert (0 = no limit), max_history_rows most recent rows.
    # Includes one bounded planner call to the configured low-cost model.
    timeout_seconds: int = 25
    max_history_rows: int = 50
    window_days: int = 30
    max_analysis_operations: int = 4
    # "llm" plans with REPORT_LLM_MODEL (heuristic when it is not set);
    # "heuristic" pins the fixed plan, so both can be compared on one batch.
    planner: str = "llm"
    allowed_columns: list[str] = field(default_factory=list)
    allowed_operations: list[str] = field(
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


@dataclass
class DelegatedResearchSettings:
    vector_store: VectorStoreResearchConfig = field(
        default_factory=VectorStoreResearchConfig
    )
    history_pandas: HistoryPandasResearchConfig = field(
        default_factory=HistoryPandasResearchConfig
    )


@dataclass
class AgentToolsConfig:
    """ "Herramientas del agente" - identical for every ReAct step with a
    tool picker (Detector, Adversarial (detector), Clasificación,
    Adversarial (clasificador)); each step reads its own copy."""

    watchlist_enabled: bool = False
    watchlist_ids: list[str] = field(default_factory=list)
    # Which alert field's value is looked up against the selected
    # watchlists' elements (e.g. "documento", "correo").
    watchlist_compare_field: str | None = None
    calculator_enabled: bool = False
    # XGBoost: decisive only in the Detector (>= fraud threshold -> fraud,
    # < uncertainty threshold -> not_fraud, band -> the LLM decides). In
    # every other step its output (score + verdict + SHAP) is evidence.
    use_xgboost_model: bool = False
    xgboost_model_id: str | None = None
    xgboost_fraud_threshold: float = 0.8
    xgboost_uncertainty_threshold: float = 0.4
    xgboost_shap_enabled: bool = True
    delegated_research: DelegatedResearchSettings = field(
        default_factory=DelegatedResearchSettings
    )


@dataclass
class ClassificationConfig(AgentToolsConfig):
    prompt: str = ""
    prompt_vars: list[str] = field(default_factory=list)
    max_thought_iterations: int = 5
    output_labels: list[str] = field(default_factory=list)


@dataclass
class DetectorConfig(ClassificationConfig):
    """Same shape as ClassificationConfig; only the XGBoost semantics
    differ (decisive here, see AgentToolsConfig)."""


@dataclass
class AdversarialConfig(AgentToolsConfig):
    prompt: str = ""
    prompt_vars: list[str] = field(default_factory=list)
    max_cycles: int = 1
    feed_feedback_to_classification: bool = True


@dataclass
class DetectorAdversarialConfig(AdversarialConfig):
    max_thought_iterations: int = 5


@dataclass
class VoicebotCategoryPrompt:
    id: str
    taxonomy_id: str
    prompt: str = ""


@dataclass
class VoicebotConfig:
    base_prompt: str = ""
    base_prompt_vars: list[str] = field(default_factory=list)
    category_prompts: list[VoicebotCategoryPrompt] = field(default_factory=list)


@dataclass
class AnalystConfig:
    # Instructions authored by the analyst for handling the alert.  The
    # playbook itself is library knowledge, not a per-segment list to select
    # at runtime.  At execution time this prompt can use {modus_operandi},
    # {playbook}, {voicebot_resources} and {analyst_resources}.
    prompt: str = ""
    prompt_vars: list[str] = field(default_factory=list)


class DocumentationStrategy(StrEnum):
    TEMPLATE = "template"
    AGENT = "agent"


@dataclass
class DocumentationConfig:
    # "one of the both components will be activated" - only the fields
    # matching `strategy` are meaningful at any given time, the other
    # pair just stays populated so switching back doesn't lose input.
    strategy: DocumentationStrategy = DocumentationStrategy.TEMPLATE
    template: str = ""
    template_vars: list[str] = field(default_factory=list)
    agent_prompt: str = ""
    agent_prompt_vars: list[str] = field(default_factory=list)


@dataclass
class PromptField:
    # A single free-text prompt plus the {variable} names it references -
    # same shape repeated verbatim across several one-off executor prompts
    # (ARIC marking comment, analyst escalation concept) that don't warrant
    # their own named dataclass each.
    prompt: str = ""
    prompt_vars: list[str] = field(default_factory=list)


@dataclass
class ExecutorConfig:
    # The four "Ejecutor" subtab sections (Wave 6): the comment the agent
    # leaves at ARIC marking time, the voicebot call (base + per-taxonomy
    # prompts), the final alert documentation, and the concept handed to
    # the analyst on escalation. Mirrors the frontend's SegmentAgentConfig
    # .executor 1:1 (configurations.functions.ts's ApiExecutorConfig) -
    # this replaces the old top-level AgentSettings.documentation and
    # AnalystConfig.voicebot fields, which the frontend never actually
    # wrote to (it always sent this same shape nested under "executor",
    # which had no matching field here - FastAPI/Pydantic's default
    # extra="ignore" silently dropped the whole thing on every save).
    aric_marking: PromptField = field(default_factory=PromptField)
    voicebot_call: VoicebotConfig = field(default_factory=VoicebotConfig)
    documentador: DocumentationConfig = field(default_factory=DocumentationConfig)
    analyst_escalation: PromptField = field(default_factory=PromptField)


@dataclass
class AgentSettings:
    deterministic: DeterministicConfig = field(default_factory=DeterministicConfig)
    profiling: ProfilingConfig = field(default_factory=ProfilingConfig)
    rubrics: list[Rubric] = field(default_factory=list)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    detector_adversarial: DetectorAdversarialConfig = field(
        default_factory=DetectorAdversarialConfig
    )
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    adversarial: AdversarialConfig = field(default_factory=AdversarialConfig)
    analyst: AnalystConfig = field(default_factory=AnalystConfig)
    executor: ExecutorConfig = field(default_factory=ExecutorConfig)
    taxonomies: list[Taxonomy] = field(default_factory=list)
    modus_operandi: list[ModusOperandi] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    example_cases: list[ExampleCase] = field(default_factory=list)
    active_fields: list[str] = field(default_factory=list)
    # Which trained model (model_port.ModelRecord.id, as str) this segment's
    # agent should use - the "modelo" subtab in configuracion/agente.
    # ModelRepository.get_active() (the FastMCP server's reload target) is a
    # separate, global concept: this field is what the frontend model
    # picker writes, and stays independent per config version.
    active_model_id: str | None = None


@dataclass
class TestSettings:
    max_test_instances: int = 4
    max_concurrent_experiments: int = 3
    experiment_timeout_minutes: int = 30
    max_stored_test_runs: int = 20
    test_cleanup_policy: TestCleanupPolicy = TestCleanupPolicy.OLDEST


class FilterConditionOperator(StrEnum):
    IN = "in"


class LogicalOperator(StrEnum):
    AND = "and"
    OR = "or"


@dataclass
class FilterCondition:
    id: str
    category: TagCategory
    operator: FilterConditionOperator = FilterConditionOperator.IN
    values: list[str] = field(default_factory=list)


@dataclass
class FilterGroup:
    # Recursive AND/OR condition tree. Two separate typed lists (conditions
    # vs. nested groups) instead of one list[FilterCondition | FilterGroup]
    # union - dataclasses/DynamoDB don't round-trip tagged unions cleanly,
    # and two concrete lists give the same recursion power.
    id: str
    operator: LogicalOperator = LogicalOperator.AND
    conditions: list[FilterCondition] = field(default_factory=list)
    groups: list[FilterGroup] = field(default_factory=list)


@dataclass
class SegmentSettings:
    # enabled defaults False: a config shouldn't silently start routing
    # alerts into a segment before an admin has built its filter.
    enabled: bool = False
    filter: FilterGroup = field(default_factory=lambda: FilterGroup(id="root"))
    monitoring: MonitoringSettings = field(default_factory=MonitoringSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    # Tie-break order when more than one enabled segment's filter matches
    # the same alert (see ResolveAlertSegmentUseCase) - admin-editable via
    # drag-and-drop on the Segmento tab, per configuration version. Lower
    # sorts first. Replaces the old fixed SegmentCode enum's declaration
    # order now that segment keys come from channel_library_port.py's
    # admin-editable catalog instead of a hardcoded enum.
    order: int = 0


def default_segments() -> dict[str, SegmentSettings]:
    # Fallback only, for callers that construct a ConfigurationRecord
    # without an explicit segments= (tests, manager.py's seed_defaults) -
    # NOT the source of truth for a real config, which gets its segments
    # dict from the caller (frontend snapshot-copies the active
    # channel_library_port.py catalog at draft-creation time, same
    # semantics as taxonomy_library_port.py's "Importar de biblioteca").
    return {
        "canales_digitales": SegmentSettings(order=0),
        "tarjetas": SegmentSettings(order=1),
    }


@dataclass
class ConfigurationRef:
    # Names one exact ConfigurationRecord version to run a test against,
    # instead of whatever ConfigurationRepository.get_active() currently
    # is - lets a test run pin a specific (possibly inactive) config, so
    # comparing multiple configurations doesn't require flipping the
    # global `active` flag per test. version None = that lineage's latest.
    configuration_id: str
    version: int | None = None


@dataclass
class ConfigurationRecord:
    # Stable id shared across every version of the same named configuration
    # ("lineage") - distinct from `version`, which increments per edit.
    configuration_id: str
    version: int
    name: str
    description: str
    active: bool
    general: GeneralSettings
    infra: InfraSettings
    test: TestSettings
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None = None
    created_by: str | None = None
    # Sticky flag, set once by ConfigurationRepository.activate and never
    # cleared - distinct from `active` (which flips back off once another
    # version takes over). Gates whether CreateConfigurationUseCase may
    # still overwrite this version in place (see update()) or must mint a
    # new one: a version that ever reached production is frozen for audit.
    ever_activated: bool = False
    ever_tested: bool = False
    # Provenance only; this schema is not owned by or coupled to the config.
    schema_version_at_creation: int | None = None
    # Immediate predecessor in the version graph; absent for the root version.
    parent_ref: ConfigurationRef | None = None
    segments: dict[str, SegmentSettings] = field(default_factory=default_segments)
