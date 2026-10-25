from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime
from typing import Any

from src.domain.configurations.entities import (
    AdversarialConfig,
    AgentSettings,
    AnalystConfig,
    ClassificationConfig,
    ConfigurationRecord,
    ConfigurationRef,
    DayProfile,
    DelegatedResearchSettings,
    DetectorAdversarialConfig,
    DetectorConfig,
    DeterministicConfig,
    DeterministicRule,
    DistributionValue,
    DocumentationConfig,
    DocumentationStrategy,
    ExampleCase,
    ExecutorConfig,
    FilterCondition,
    FilterConditionOperator,
    FilterGroup,
    Flag,
    FlagType,
    GeneralSettings,
    HistoryPandasResearchConfig,
    InfraSettings,
    ModusOperandi,
    MonitoringSettings,
    ProfilingConfig,
    ProfilingPromptMode,
    ProfilingStrategy,
    ProfilingStrategyKey,
    PromptField,
    ResolutionTag,
    Rubric,
    RuleCondition,
    SamplingCriterion,
    SamplingIntervalUnit,
    SegmentSettings,
    ShortageBehavior,
    TagCategory,
    Taxonomy,
    TestCleanupPolicy,
    TestSettings,
    VectorStoreResearchConfig,
    VoicebotCategoryPrompt,
    VoicebotConfig,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)


def _owned_item(
    configuration_id: str, version: int, payload: dict[str, Any]
) -> dict[str, Any]:
    return {"configuration_id": configuration_id, "version": version, **payload}


def _to_item(config: ConfigurationRecord) -> dict[str, Any]:
    # No "segments" here - the two segment objects are their own table
    # (configuration_segments), born alongside this item in create().
    return {
        "configuration_id": config.configuration_id,
        "version": config.version,
        "name": config.name,
        "description": config.description,
        "active": config.active,
        "ever_activated": config.ever_activated,
        "ever_tested": config.ever_tested,
        "parent_ref": (
            {
                "configuration_id": config.parent_ref.configuration_id,
                "version": config.parent_ref.version,
            }
            if config.parent_ref is not None
            else None
        ),
        "schema_version_at_creation": config.schema_version_at_creation,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
        "activated_at": config.activated_at.isoformat()
        if config.activated_at
        else None,
        "created_by": config.created_by,
    }


def _segment_to_item(segment: SegmentSettings) -> dict[str, Any]:
    # asdict() the whole segment, then strip whatever now lives in its own
    # table(s) - asdict picks up any future scalar field automatically, so
    # only the extracted collections need naming here.
    item = asdict(segment)
    del item["filter"]  # own tables now (configuration_filter_groups/_conditions)
    del item["monitoring"]["sampling_criteria"]
    del item["agent"]["profiling"]["strategies"]
    # field_enrichment is a plain dict (a FeatureConfiguration - see
    # feature_recipe.py), not a dataclass list like the other extracted
    # collections here, so it stays inline on this item rather than in its
    # own table.
    item["agent"]["profiling"]["field_enrichment"] = (
        segment.agent.profiling.field_enrichment
    )
    for key in ("taxonomies", "modus_operandi", "flags", "example_cases"):
        del item["agent"][key]
    del item["agent"]["executor"]["voicebot_call"]["category_prompts"]
    # boto3's resource layer rejects native float anywhere in the item
    # (detector xgboost thresholds, rule scores, field_enrichment, ...), so
    # convert the whole tree to Decimal in one pass instead of per-field.
    return to_dynamodb(item)


def _from_item(item: dict[str, Any]) -> ConfigurationRecord:
    # general/infra/ops/test/segments are placeholders here (segments
    # default via ConfigurationRecord's own default_factory) -
    # DynamoConfigurationRepository._hydrate overwrites all of them from
    # their own tables right after this call.
    return ConfigurationRecord(
        configuration_id=item["configuration_id"],
        version=int(item["version"]),
        name=item["name"],
        description=item.get("description") or "",
        active=bool(item.get("active", False)),
        ever_activated=bool(item.get("ever_activated", False)),
        ever_tested=bool(item.get("ever_tested", False)),
        schema_version_at_creation=(
            int(item["schema_version_at_creation"])
            if item.get("schema_version_at_creation") is not None
            else None
        ),
        parent_ref=(
            ConfigurationRef(
                configuration_id=item["parent_ref"]["configuration_id"],
                version=int(item["parent_ref"]["version"]),
            )
            if item.get("parent_ref")
            else None
        ),
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=TestSettings(),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        activated_at=(
            datetime.fromisoformat(item["activated_at"])
            if item.get("activated_at")
            else None
        ),
        created_by=item.get("created_by"),
    )


# --- 1:1 section item <-> dataclass -------------------------------------


def _general_from_item(item: dict[str, Any]) -> GeneralSettings:
    # Legacy agent/analyst/voicebot on-off keys on old rows are ignored:
    # those switches live in OperationalSettings now.
    return GeneralSettings(
        migration_window_enabled=bool(item.get("migration_window_enabled", False)),
        migration_window_datetime=str(
            item.get("migration_window_datetime", "2000-01-01T02:00")
        ),
    )


def _infra_from_item(item: dict[str, Any]) -> InfraSettings:
    return InfraSettings(
        max_instances=int(item.get("max_instances", 8)),
        auto_scale=bool(item.get("auto_scale", True)),
        fraud_history_db_retention_days=int(
            item.get("fraud_history_db_retention_days", 90)
        ),
        fraud_history_cold_storage_retention_months=int(
            item.get("fraud_history_cold_storage_retention_months", 24)
        ),
    )


def _evaluation_from_item(item: dict[str, Any]) -> TestSettings:
    return TestSettings(
        max_test_instances=int(item.get("max_test_instances", 4)),
        max_concurrent_experiments=int(item.get("max_concurrent_experiments", 3)),
        experiment_timeout_minutes=int(item.get("experiment_timeout_minutes", 30)),
        max_stored_test_runs=int(item.get("max_stored_test_runs", 20)),
        test_cleanup_policy=TestCleanupPolicy(
            item.get("test_cleanup_policy", "oldest")
        ),
    )


def _shortage_behavior_from_item(item: dict[str, Any]) -> ShortageBehavior:
    return ShortageBehavior(
        resolution_tag=ResolutionTag(item.get("resolution_tag", "block_soft")),
        resolution_method_id=item.get("resolution_method_id"),
    )


# --- sub-entity item <-> dataclass ---------------------------------------
# Each of these decodes one row from its own dedicated table (or, for the
# _from_item test helpers below, a hand-built dict shaped the same way).


def _day_profile_from_item(item: dict[str, Any]) -> DayProfile:
    return DayProfile(
        id=item["id"],
        name=item["name"],
        description=item.get("description") or "",
        hourly=[int(h) for h in item.get("hourly") or []],
    )


def _taxonomy_from_item(item: dict[str, Any]) -> Taxonomy:
    return Taxonomy(
        id=item["id"],
        code=item["code"],
        name=item["name"],
        description=item.get("description") or "",
        variables=list(item.get("variables") or []),
        examples=list(item.get("examples") or []),
        active=bool(item.get("active", True)),
        segmento=item.get("segmento") or "",
    )


def _modus_operandi_from_item(item: dict[str, Any]) -> ModusOperandi:
    return ModusOperandi(
        id=item["id"],
        title=item["title"],
        narrative=item.get("narrative") or "",
        taxonomy_id=item["taxonomy_id"],
        evolved_variables=list(item.get("evolved_variables") or []),
        active=bool(item.get("active", True)),
        segmento=item.get("segmento") or "",
    )


def _flag_from_item(item: dict[str, Any]) -> Flag:
    return Flag(
        id=item["id"],
        flag_type=FlagType(item["flag_type"]),
        name=item["name"],
        description=item.get("description") or "",
        evolved_variables=list(item.get("evolved_variables") or []),
        modus_operandi_ids=list(item.get("modus_operandi_ids") or []),
        segmento=item.get("segmento") or "",
    )


def _example_case_from_item(item: dict[str, Any]) -> ExampleCase:
    return ExampleCase(
        id=item["id"],
        text=item.get("text") or "",
        modus_operandi_id=item["modus_operandi_id"],
        taxonomy_id=item["taxonomy_id"],
        segmento=item.get("segmento") or "",
    )


def _voicebot_category_prompt_from_item(item: dict[str, Any]) -> VoicebotCategoryPrompt:
    return VoicebotCategoryPrompt(
        id=item["id"],
        taxonomy_id=item["taxonomy_id"],
        prompt=item.get("prompt") or "",
    )


def _sampling_criterion_from_item(item: dict[str, Any]) -> SamplingCriterion:
    return SamplingCriterion(
        id=item["id"],
        name=item["name"],
        values=[_distribution_value_from_item(v) for v in item.get("values") or []],
    )


def _distribution_value_from_item(item: dict[str, Any]) -> DistributionValue:
    return DistributionValue(id=item["id"], label=item["label"], pct=int(item["pct"]))


def _filter_condition_from_item(item: dict[str, Any]) -> FilterCondition:
    return FilterCondition(
        id=item["id"],
        category=TagCategory(item["category"]),
        operator=FilterConditionOperator(item.get("operator", "in")),
        values=list(item.get("values") or []),
    )


# --- configuration_segments row sub-sections ------------------------------


def _segment_settings_from_item(item: dict[str, Any]) -> SegmentSettings:
    return SegmentSettings(
        enabled=bool(item.get("enabled", False)),
        filter=FilterGroup(id="root"),  # own tables - filled in by _hydrate
        monitoring=_monitoring_from_item(item.get("monitoring") or {}),
        agent=_agent_from_item(item.get("agent") or {}),
        # Pre-migration rows (written before this field existed) default to
        # 0 for every segment - same tie-break result as the old fixed
        # SegmentCode enum only for a 1-segment config; a multi-segment
        # pre-migration config falls back to dict order, which is no
        # longer guaranteed meaningful. No such records exist outside local
        # dev data at the time of this migration.
        order=int(item.get("order", 0)),
    )


def _monitoring_from_item(monitoring_item: dict[str, Any]) -> MonitoringSettings:
    # sampling_criteria isn't stored on this item (own tables, see
    # DynamoConfigurationRepository._hydrate) - defaults to [] here, the
    # caller fills it in after querying configuration_sampling_criteria.
    return MonitoringSettings(
        sampling_interval_value=int(monitoring_item.get("sampling_interval_value", 30)),
        sampling_interval_unit=SamplingIntervalUnit(
            monitoring_item.get("sampling_interval_unit", "minutes")
        ),
        max_samples=int(monitoring_item.get("max_samples", 200)),
        prompt_clasificacion=monitoring_item.get("prompt_clasificacion") or "",
        prompt_clasificacion_vars=list(
            monitoring_item.get("prompt_clasificacion_vars") or []
        ),
        prompt_analista=monitoring_item.get("prompt_analista") or "",
        prompt_analista_vars=list(monitoring_item.get("prompt_analista_vars") or []),
        prompt_monitoreo=monitoring_item.get("prompt_monitoreo") or "",
        prompt_monitoreo_vars=list(monitoring_item.get("prompt_monitoreo_vars") or []),
    )


def _kwargs_for(cls: type, item: dict[str, Any]) -> dict[str, Any]:
    # Drops keys the item still carries under an old name after a dataclass
    # field rename (e.g. vector_store_instance_ids -> vector_store_instance_id)
    # so hydrating a pre-migration row never hard-fails with an unexpected
    # keyword argument. Symmetric with the rest of this module's .get()-based
    # tolerance for rows *missing* new fields.
    known = {f.name for f in fields(cls)}
    return {key: value for key, value in item.items() if key in known}


def _delegated_research_from_item(
    item: dict[str, Any] | None,
) -> DelegatedResearchSettings:
    """Hydrate nested research config while accepting pre-feature rows."""
    item = item or {}
    vector_store = item.get("vector_store") or {}
    history_pandas = item.get("history_pandas") or {}
    return DelegatedResearchSettings(
        vector_store=VectorStoreResearchConfig(
            **_kwargs_for(VectorStoreResearchConfig, vector_store)
        ),
        history_pandas=HistoryPandasResearchConfig(
            **_kwargs_for(HistoryPandasResearchConfig, history_pandas)
        ),
    )


def _tools_config_from_item(cls: type, item: dict[str, Any]) -> Any:
    """Hydrate any AgentToolsConfig subclass (Detector, Classification and
    both Adversarials)."""
    item = from_dynamodb(item)
    payload = _kwargs_for(cls, item)
    research = _delegated_research_from_item(item.get("delegated_research"))
    # Pre-unification rows: the old direct "Base de conocimiento" switch
    # (top-level vector_store_enabled/_instance_id) is now the vector-store
    # research tool - carry it over so a saved selection keeps working.
    legacy_id = item.get("vector_store_instance_id")
    if (
        item.get("vector_store_enabled")
        and legacy_id
        and not research.vector_store.vector_store_instance_id
    ):
        research.vector_store.enabled = True
        research.vector_store.vector_store_instance_id = legacy_id
    payload["delegated_research"] = research
    return cls(**payload)


def _agent_from_item(agent_item: dict[str, Any]) -> AgentSettings:
    # taxonomies/modus_operandi/flags/example_cases and
    # executor.voicebot_call.category_prompts aren't
    # stored on this item (their own tables, see
    # DynamoConfigurationRepository._hydrate) - default to [] here, the
    # caller fills them in after querying.
    return AgentSettings(
        deterministic=_deterministic_from_item(agent_item.get("deterministic") or {}),
        profiling=_profiling_from_item(agent_item.get("profiling") or {}),
        rubrics=[
            Rubric(
                id=item.get("id") or "",
                name=item.get("name") or "",
                conditions=[
                    RuleCondition(**from_dynamodb(condition))
                    for condition in item.get("conditions") or []
                ],
            )
            for item in agent_item.get("rubrics") or []
        ],
        detector=_tools_config_from_item(
            DetectorConfig, agent_item.get("detector") or {}
        ),
        detector_adversarial=_tools_config_from_item(
            DetectorAdversarialConfig, agent_item.get("detector_adversarial") or {}
        ),
        classification=_tools_config_from_item(
            ClassificationConfig, agent_item.get("classification") or {}
        ),
        adversarial=_tools_config_from_item(
            AdversarialConfig, agent_item.get("adversarial") or {}
        ),
        analyst=AnalystConfig(
            prompt=(agent_item.get("analyst") or {}).get("prompt") or "",
            prompt_vars=list(
                (agent_item.get("analyst") or {}).get("prompt_vars") or []
            ),
        ),
        executor=_executor_from_item(agent_item.get("executor") or {}),
        active_fields=list(agent_item.get("active_fields") or []),
        active_model_id=agent_item.get("active_model_id"),
    )


def _voicebot_from_item(item: dict[str, Any]) -> VoicebotConfig:
    return VoicebotConfig(
        base_prompt=item.get("base_prompt") or "",
        base_prompt_vars=list(item.get("base_prompt_vars") or []),
    )


def _documentation_from_item(item: dict[str, Any]) -> DocumentationConfig:
    return DocumentationConfig(
        strategy=DocumentationStrategy(item.get("strategy", "template")),
        template=item.get("template") or "",
        template_vars=list(item.get("template_vars") or []),
        agent_prompt=item.get("agent_prompt") or "",
        agent_prompt_vars=list(item.get("agent_prompt_vars") or []),
    )


def _prompt_field_from_item(item: dict[str, Any]) -> PromptField:
    return PromptField(
        prompt=item.get("prompt") or "",
        prompt_vars=list(item.get("prompt_vars") or []),
    )


def _executor_from_item(item: dict[str, Any]) -> ExecutorConfig:
    return ExecutorConfig(
        aric_marking=_prompt_field_from_item(item.get("aric_marking") or {}),
        voicebot_call=_voicebot_from_item(item.get("voicebot_call") or {}),
        documentador=_documentation_from_item(item.get("documentador") or {}),
        analyst_escalation=_prompt_field_from_item(
            item.get("analyst_escalation") or {}
        ),
    )


def _profiling_from_item(profiling_item: dict[str, Any]) -> ProfilingConfig:
    strategies_raw = profiling_item.get("strategies")
    profiling = ProfilingConfig(
        strategies=(
            [_profiling_strategy_from_item(s) for s in strategies_raw]
            if strategies_raw
            else [ProfilingStrategy(key=key) for key in ProfilingStrategyKey]
        ),
    )
    field_enrichment_raw = profiling_item.get("field_enrichment")
    if field_enrichment_raw:
        profiling.field_enrichment = from_dynamodb(field_enrichment_raw)
    return profiling


def _deterministic_from_item(item: dict[str, Any]) -> DeterministicConfig:
    return DeterministicConfig(
        # `or DeterministicConfig().alert_filter` also heals rows saved
        # before _default_alert_filter existed, when the default was a bare
        # `{}` - the frontend's FilterGroup mapper crashes on that shape, so
        # missing/empty here must fall back to the well-formed default, not
        # `{}` itself.
        alert_filter=from_dynamodb(
            item.get("alert_filter") or DeterministicConfig().alert_filter
        ),
        field_enrichment=from_dynamodb(
            item.get("field_enrichment") or DeterministicConfig().field_enrichment
        ),
        rules=[
            DeterministicRule(**from_dynamodb(rule)) for rule in item.get("rules") or []
        ],
    )


def _profiling_strategy_from_item(item: dict[str, Any]) -> ProfilingStrategy:
    return ProfilingStrategy(
        key=ProfilingStrategyKey(item["key"]),
        main_prompt=item.get("main_prompt") or "",
        main_prompt_vars=list(item.get("main_prompt_vars") or []),
        main_prompt_mode=ProfilingPromptMode(
            item.get("main_prompt_mode") or ProfilingPromptMode.FSTRING
        ),
        categorization_prompt=item.get("categorization_prompt") or "",
        categorization_prompt_vars=list(item.get("categorization_prompt_vars") or []),
        use_pandas_history_mcp=bool(item.get("use_pandas_history_mcp", False)),
    )
