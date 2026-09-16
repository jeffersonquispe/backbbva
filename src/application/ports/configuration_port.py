from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from src.application.ports.tag_catalog_port import TagCategory


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


class ResolutionTag(StrEnum):
    # Fixed dimension a ResolutionMethod catalog entry maps onto (see
    # resolution_method_catalog_port.py) - the workflow will eventually
    # branch on this. BLOCK_SOFT/BLOCK_HARD exist only for ShortageBehavior
    # below; AnalystPlaybook only ever uses the first three.
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
    # Same catalog as AnalystPlaybook.resolution_method_id below - an admin
    # names methods once (ResolutionMethodCatalogRepository) and reuses them
    # here. resolution_tag stays denormalized for the same reason as
    # AnalystPlaybook's; resolution_method_id is nullable so a freshly
    # created config still has a sane default (block_soft) until an admin
    # actually picks a method.
    resolution_tag: ResolutionTag = ResolutionTag.BLOCK_SOFT
    resolution_method_id: str | None = None


@dataclass
class GeneralSettings:
    agent_enabled: bool = True
    migration_window_enabled: bool = False
    # ISO datetime string ("YYYY-MM-DDTHH:MM"), same format the frontend's
    # <input type="datetime-local"> produces - stored as-is, no parsing.
    migration_window_datetime: str = "2000-01-01T02:00"
    analyst_escalation_enabled: bool = True
    voicebot_escalation_enabled: bool = True


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
class OpsSettings:
    voicebot_max_concurrent_calls: int = 40
    analyst_capacity: AnalystCapacity = field(default_factory=AnalystCapacity)
    queue_max_lifetime_value: int = 60
    queue_max_lifetime_unit: SamplingIntervalUnit = SamplingIntervalUnit.MINUTES
    queue_discard_amount_threshold: float = 0
    # When enabled, alerts are filtered by whether their triggered_rule tag
    # belongs to queue_allowed_triggered_rules (per queue_rule_filter_mode) -
    # non-matching alerts are discarded instead of queued, same as
    # queue_discard_amount_threshold's amount-based discard.
    queue_rule_filter_enabled: bool = False
    queue_rule_filter_mode: ListMembershipMode = ListMembershipMode.BELONGS
    queue_allowed_triggered_rules: list[str] = field(default_factory=list)
    # What to do with an alert instead of queuing it normally, whenever any
    # of the three queue-discard paths above trigger (lifetime skip, amount
    # threshold, or rule filter) - same resolution-method catalog as
    # voicebot/analyst shortage below.
    queue_discard_behavior: ShortageBehavior = field(default_factory=ShortageBehavior)
    voicebot_shortage_behavior: ShortageBehavior = field(
        default_factory=ShortageBehavior
    )
    analyst_shortage_behavior: ShortageBehavior = field(
        default_factory=ShortageBehavior
    )


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
    field_enrichment: dict[str, Any] = field(
        default_factory=_default_field_enrichment
    )
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


class VectorStoreTool(StrEnum):
    # Which fraud-knowledge document types the classification agent may
    # retrieve from - deliberately a separate enum from fraud_knowledge_
    # port.py's DocumentType (same values, different concept: "what can
    # this agent search" vs. "what type is this OpenSearch document") so
    # this domain-layer port doesn't import the vector-store layer.
    TAXONOMIA = "taxonomia"
    MODUS_OPERANDI = "modus_operandi"
    SIMILAR_CASE = "similar_case"
    RED_FLAG = "red_flag"
    YELLOW_FLAG = "yellow_flag"


class BuiltInTool(StrEnum):
    BLACKLIST = "blacklist"
    WHITELIST = "whitelist"
    CALCULATOR = "calculator"


@dataclass
class ClassificationConfig:
    vector_store_tools: list[VectorStoreTool] = field(default_factory=list)
    built_in_tools: list[BuiltInTool] = field(default_factory=list)
    prompt: str = ""
    prompt_vars: list[str] = field(default_factory=list)


@dataclass
class AdversarialConfig:
    prompt: str = ""
    prompt_vars: list[str] = field(default_factory=list)
    max_cycles: int = 1
    feed_feedback_to_classification: bool = True


@dataclass
class AnalystPlaybook:
    # Config-time definition, distinct from fraud_playbook_port.py's
    # FraudPlaybookRecord - that one is a different, already-live runtime
    # concept (a flat {title, steps} doc read by analyst_review_alert.py
    # at alert-review time, keyed 1:1 by classification string). This one
    # is versioned per segment alongside taxonomies/flags/etc, like every
    # other AgentSettings sub-config, and not read by the workflow yet.
    id: str
    name: str
    strategy: str = ""
    resolution_tag: ResolutionTag = ResolutionTag.SCALE_TO_ANALYST
    # Which resolution_method_catalog entry the admin picked in the UI -
    # resolution_tag is kept denormalized alongside it (the catalog entry's
    # mapped tag, copied at save time) so this field stays optional and
    # anything reading resolution_tag today keeps working unchanged.
    resolution_method_id: str | None = None


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
    playbooks: list[AnalystPlaybook] = field(default_factory=list)
    voicebot: VoicebotConfig = field(default_factory=VoicebotConfig)


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
class AgentSettings:
    deterministic: DeterministicConfig = field(default_factory=DeterministicConfig)
    profiling: ProfilingConfig = field(default_factory=ProfilingConfig)
    rubrics: list[Rubric] = field(default_factory=list)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    adversarial: AdversarialConfig = field(default_factory=AdversarialConfig)
    analyst: AnalystConfig = field(default_factory=AnalystConfig)
    documentation: DocumentationConfig = field(default_factory=DocumentationConfig)
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
    groups: list["FilterGroup"] = field(default_factory=list)


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
    ops: OpsSettings
    test: TestSettings
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    # Sticky flag, set once by ConfigurationRepository.activate and never
    # cleared - distinct from `active` (which flips back off once another
    # version takes over). Gates whether CreateConfigurationUseCase may
    # still overwrite this version in place (see update()) or must mint a
    # new one: a version that ever reached production is frozen for audit.
    ever_activated: bool = False
    ever_tested: bool = False
    segments: dict[str, SegmentSettings] = field(default_factory=default_segments)


class ConfigurationRepository(Protocol):
    def create(self, config: ConfigurationRecord) -> ConfigurationRecord:
        ...

    def mark_tested(self, configuration_id: str, version: int) -> None:
        ...

    def update(self, config: ConfigurationRecord) -> ConfigurationRecord:
        """Overwrite an existing (configuration_id, version) in place -
        every child row is replaced, matching create()'s shape exactly.
        Callers must only use this on a version that has never been
        activated (see ConfigurationRecord.ever_activated); this method
        itself does not enforce that."""
        ...

    def get(
        self, configuration_id: str, version: int
    ) -> ConfigurationRecord | None:
        ...

    def get_latest_version(
        self, configuration_id: str
    ) -> ConfigurationRecord | None:
        ...

    def get_active(self) -> ConfigurationRecord | None:
        ...

    def list_latest(self) -> list[ConfigurationRecord]:
        ...

    def list_versions(self, configuration_id: str) -> list[ConfigurationRecord]:
        ...

    def activate(self, configuration_id: str, version: int) -> ConfigurationRecord:
        ...
