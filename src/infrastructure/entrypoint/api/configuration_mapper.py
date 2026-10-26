"""Conversions between configuration API schemas and domain records."""

from __future__ import annotations

from typing import Any

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.use_cases.configurations.get_configuration_graph import (
    ConfigurationGraphNode,
)
from src.domain.configurations.entities import (
    AdversarialConfig,
    AgentSettings,
    AnalystConfig,
    ClassificationConfig,
    ConfigurationRecord,
    ConfigurationRef,
    DelegatedResearchSettings,
    DetectorAdversarialConfig,
    DetectorConfig,
    DeterministicConfig,
    DeterministicRule,
    DistributionValue,
    DocumentationConfig,
    ExampleCase,
    ExecutorConfig,
    FilterCondition,
    FilterGroup,
    Flag,
    GeneralSettings,
    HistoryPandasResearchConfig,
    InfraSettings,
    ModusOperandi,
    MonitoringSettings,
    ProfilingConfig,
    ProfilingStrategy,
    PromptField,
    Rubric,
    RuleCondition,
    SamplingCriterion,
    SegmentSettings,
    Taxonomy,
    TestSettings,
    VectorStoreResearchConfig,
    VoicebotCategoryPrompt,
    VoicebotConfig,
)
from src.infrastructure.entrypoint.api.schemas import (
    AdversarialConfigSchema,
    AgentSettingsSchema,
    AnalystConfigSchema,
    ClassificationConfigSchema,
    ConfigurationDetailResponse,
    ConfigurationGraphNodeResponse,
    ConfigurationSummaryResponse,
    CreateConfigurationRequest,
    DelegatedResearchSettingsSchema,
    DetectorAdversarialConfigSchema,
    DetectorConfigSchema,
    DeterministicConfigSchema,
    DeterministicRuleSchema,
    DistributionValueSchema,
    DocumentationConfigSchema,
    ExampleCaseSchema,
    ExecutorConfigSchema,
    FilterConditionSchema,
    FilterGroupSchema,
    FlagSchema,
    GeneralSettingsSchema,
    InfraSettingsSchema,
    ModusOperandiSchema,
    MonitoringSettingsSchema,
    ProfilingConfigSchema,
    ProfilingStrategySchema,
    PromptFieldSchema,
    RubricSchema,
    RuleConditionSchema,
    SamplingCriterionSchema,
    SegmentSettingsSchema,
    TaxonomySchema,
    TestSettingsSchema,
    VoicebotCategoryPromptSchema,
    VoicebotConfigSchema,
)


def input_from_request(
    request: CreateConfigurationRequest,
) -> CreateConfigurationInput:
    return CreateConfigurationInput(
        name=request.name,
        configuration_id=request.configuration_id,
        based_on_version=request.based_on_version,
        parent_ref=(
            ConfigurationRef(
                configuration_id=str(request.parent_ref["configuration_id"]),
                version=int(request.parent_ref["version"]),
            )
            if request.parent_ref is not None
            else None
        ),
        description=request.description,
        general=_general_from_schema(request.general),
        infra=_infra_from_schema(request.infra),
        test=_test_from_schema(request.test),
        created_by=request.created_by,
        segments={
            code: _segment_settings_from_schema(schema)
            for code, schema in request.segments.items()
        },
    )


def to_summary_response(record: ConfigurationRecord) -> ConfigurationSummaryResponse:
    return ConfigurationSummaryResponse(
        configuration_id=record.configuration_id,
        version=record.version,
        name=record.name,
        description=record.description,
        active=record.active,
        ever_activated=record.ever_activated,
        ever_tested=record.ever_tested,
        created_at=record.created_at,
        updated_at=record.updated_at,
        parent_ref=(
            {
                "configuration_id": record.parent_ref.configuration_id,
                "version": record.parent_ref.version,
            }
            if record.parent_ref is not None
            else None
        ),
    )


def to_graph_node_response(
    node: ConfigurationGraphNode,
) -> ConfigurationGraphNodeResponse:
    return ConfigurationGraphNodeResponse(
        **to_summary_response(node.record).model_dump(),
        promotion_comment=node.promotion_comment,
    )


def to_detail_response(record: ConfigurationRecord) -> ConfigurationDetailResponse:
    return ConfigurationDetailResponse(
        configuration_id=record.configuration_id,
        version=record.version,
        name=record.name,
        description=record.description,
        active=record.active,
        ever_activated=record.ever_activated,
        ever_tested=record.ever_tested,
        created_at=record.created_at,
        updated_at=record.updated_at,
        parent_ref=(
            {
                "configuration_id": record.parent_ref.configuration_id,
                "version": record.parent_ref.version,
            }
            if record.parent_ref is not None
            else None
        ),
        created_by=record.created_by,
        schema_version_at_creation=record.schema_version_at_creation,
        general=GeneralSettingsSchema(**record.general.__dict__),
        infra=InfraSettingsSchema(**record.infra.__dict__),
        test=TestSettingsSchema(**record.test.__dict__),
        segments={
            code: _segment_settings_to_schema(settings)
            for code, settings in record.segments.items()
        },
    )


def _monitoring_to_schema(monitoring: MonitoringSettings) -> MonitoringSettingsSchema:
    return MonitoringSettingsSchema(
        sampling_interval_value=monitoring.sampling_interval_value,
        sampling_interval_unit=monitoring.sampling_interval_unit,
        sampling_criteria=[
            SamplingCriterionSchema(
                id=c.id,
                name=c.name,
                values=[DistributionValueSchema(**v.__dict__) for v in c.values],
            )
            for c in monitoring.sampling_criteria
        ],
        max_samples=monitoring.max_samples,
        prompt_clasificacion=monitoring.prompt_clasificacion,
        prompt_clasificacion_vars=monitoring.prompt_clasificacion_vars,
        prompt_analista=monitoring.prompt_analista,
        prompt_analista_vars=monitoring.prompt_analista_vars,
        prompt_monitoreo=monitoring.prompt_monitoreo,
        prompt_monitoreo_vars=monitoring.prompt_monitoreo_vars,
    )


def _flag_to_schema(flag: Flag) -> FlagSchema:
    return FlagSchema(**flag.__dict__)


def _profiling_to_schema(profiling: ProfilingConfig) -> ProfilingConfigSchema:
    return ProfilingConfigSchema(
        field_enrichment=profiling.field_enrichment,
        strategies=[
            ProfilingStrategySchema(**s.__dict__) for s in profiling.strategies
        ],
    )


def _tools_config_to_schema(config: Any, schema_cls: type) -> Any:
    # Shared by the four AgentToolsConfig subclasses (Detector, its
    # Adversarial, Classification, its Adversarial).
    research = config.delegated_research
    return schema_cls(
        **{
            **config.__dict__,
            "delegated_research": DelegatedResearchSettingsSchema(
                vector_store=research.vector_store.__dict__,
                history_pandas=research.history_pandas.__dict__,
            ),
        }
    )


def _classification_to_schema(
    classification: ClassificationConfig,
) -> ClassificationConfigSchema:
    return _tools_config_to_schema(classification, ClassificationConfigSchema)


def _adversarial_to_schema(adversarial: AdversarialConfig) -> AdversarialConfigSchema:
    return _tools_config_to_schema(adversarial, AdversarialConfigSchema)


def _voicebot_to_schema(voicebot: VoicebotConfig) -> VoicebotConfigSchema:
    return VoicebotConfigSchema(
        base_prompt=voicebot.base_prompt,
        base_prompt_vars=voicebot.base_prompt_vars,
        category_prompts=[
            VoicebotCategoryPromptSchema(**c.__dict__)
            for c in voicebot.category_prompts
        ],
    )


def _analyst_to_schema(analyst: AnalystConfig) -> AnalystConfigSchema:
    return AnalystConfigSchema(
        prompt=analyst.prompt,
        prompt_vars=analyst.prompt_vars,
    )


def _documentation_to_schema(
    documentation: DocumentationConfig,
) -> DocumentationConfigSchema:
    return DocumentationConfigSchema(**documentation.__dict__)


def _executor_to_schema(executor: ExecutorConfig) -> ExecutorConfigSchema:
    return ExecutorConfigSchema(
        aric_marking=PromptFieldSchema(**executor.aric_marking.__dict__),
        voicebot_call=_voicebot_to_schema(executor.voicebot_call),
        documentador=_documentation_to_schema(executor.documentador),
        analyst_escalation=PromptFieldSchema(**executor.analyst_escalation.__dict__),
    )


def _agent_to_schema(agent: AgentSettings) -> AgentSettingsSchema:
    return AgentSettingsSchema(
        deterministic=DeterministicConfigSchema(
            alert_filter=agent.deterministic.alert_filter,
            field_enrichment=agent.deterministic.field_enrichment,
            rules=[
                DeterministicRuleSchema(**rule.__dict__)
                for rule in agent.deterministic.rules
            ],
        ),
        profiling=_profiling_to_schema(agent.profiling),
        rubrics=[
            RubricSchema(
                id=rubric.id,
                name=rubric.name,
                conditions=[
                    RuleConditionSchema(**condition.__dict__)
                    for condition in rubric.conditions
                ],
            )
            for rubric in agent.rubrics
        ],
        detector=_tools_config_to_schema(agent.detector, DetectorConfigSchema),
        detector_adversarial=_tools_config_to_schema(
            agent.detector_adversarial, DetectorAdversarialConfigSchema
        ),
        classification=_classification_to_schema(agent.classification),
        adversarial=_adversarial_to_schema(agent.adversarial),
        analyst=_analyst_to_schema(agent.analyst),
        executor=_executor_to_schema(agent.executor),
        taxonomies=[TaxonomySchema(**t.__dict__) for t in agent.taxonomies],
        modus_operandi=[
            ModusOperandiSchema(**m.__dict__) for m in agent.modus_operandi
        ],
        flags=[_flag_to_schema(f) for f in agent.flags],
        example_cases=[ExampleCaseSchema(**e.__dict__) for e in agent.example_cases],
        active_fields=agent.active_fields,
        active_model_id=agent.active_model_id,
    )


def _general_from_schema(schema: GeneralSettingsSchema) -> GeneralSettings:
    return GeneralSettings(**schema.model_dump())


def _infra_from_schema(schema: InfraSettingsSchema) -> InfraSettings:
    return InfraSettings(**schema.model_dump())


def _monitoring_from_schema(schema: MonitoringSettingsSchema) -> MonitoringSettings:
    return MonitoringSettings(
        sampling_interval_value=schema.sampling_interval_value,
        sampling_interval_unit=schema.sampling_interval_unit,
        sampling_criteria=[
            SamplingCriterion(
                id=c.id,
                name=c.name,
                values=[DistributionValue(**v.model_dump()) for v in c.values],
            )
            for c in schema.sampling_criteria
        ],
        max_samples=schema.max_samples,
        prompt_clasificacion=schema.prompt_clasificacion,
        prompt_clasificacion_vars=schema.prompt_clasificacion_vars,
        prompt_analista=schema.prompt_analista,
        prompt_analista_vars=schema.prompt_analista_vars,
        prompt_monitoreo=schema.prompt_monitoreo,
        prompt_monitoreo_vars=schema.prompt_monitoreo_vars,
    )


def _flag_from_schema(schema: FlagSchema) -> Flag:
    return Flag(**schema.model_dump())


def _profiling_from_schema(schema: ProfilingConfigSchema) -> ProfilingConfig:
    return ProfilingConfig(
        field_enrichment=schema.field_enrichment,
        strategies=[ProfilingStrategy(**s.model_dump()) for s in schema.strategies],
    )


def _tools_config_from_schema(schema: Any, config_cls: type) -> Any:
    payload = schema.model_dump()
    research = payload.pop("delegated_research")
    return config_cls(
        **payload,
        delegated_research=DelegatedResearchSettings(
            vector_store=VectorStoreResearchConfig(**research["vector_store"]),
            history_pandas=HistoryPandasResearchConfig(**research["history_pandas"]),
        ),
    )


def _classification_from_schema(
    schema: ClassificationConfigSchema,
) -> ClassificationConfig:
    return _tools_config_from_schema(schema, ClassificationConfig)


def _detector_from_schema(schema: DetectorConfigSchema) -> DetectorConfig:
    return _tools_config_from_schema(schema, DetectorConfig)


def _adversarial_from_schema(schema: AdversarialConfigSchema) -> AdversarialConfig:
    return _tools_config_from_schema(schema, AdversarialConfig)


def _voicebot_from_schema(schema: VoicebotConfigSchema) -> VoicebotConfig:
    return VoicebotConfig(
        base_prompt=schema.base_prompt,
        base_prompt_vars=schema.base_prompt_vars,
        category_prompts=[
            VoicebotCategoryPrompt(**c.model_dump()) for c in schema.category_prompts
        ],
    )


def _analyst_from_schema(schema: AnalystConfigSchema) -> AnalystConfig:
    return AnalystConfig(
        prompt=schema.prompt,
        prompt_vars=schema.prompt_vars,
    )


def _documentation_from_schema(
    schema: DocumentationConfigSchema,
) -> DocumentationConfig:
    return DocumentationConfig(**schema.model_dump())


def _executor_from_schema(schema: ExecutorConfigSchema) -> ExecutorConfig:
    return ExecutorConfig(
        aric_marking=PromptField(**schema.aric_marking.model_dump()),
        voicebot_call=_voicebot_from_schema(schema.voicebot_call),
        documentador=_documentation_from_schema(schema.documentador),
        analyst_escalation=PromptField(**schema.analyst_escalation.model_dump()),
    )


def _agent_from_schema(schema: AgentSettingsSchema) -> AgentSettings:
    return AgentSettings(
        deterministic=DeterministicConfig(
            alert_filter=schema.deterministic.alert_filter,
            field_enrichment=schema.deterministic.field_enrichment,
            rules=[
                DeterministicRule(**rule.model_dump())
                for rule in schema.deterministic.rules
            ],
        ),
        profiling=_profiling_from_schema(schema.profiling),
        rubrics=[
            Rubric(
                id=rubric.id,
                name=rubric.name,
                conditions=[
                    RuleCondition(**condition.model_dump())
                    for condition in rubric.conditions
                ],
            )
            for rubric in schema.rubrics
        ],
        detector=_detector_from_schema(schema.detector),
        detector_adversarial=_tools_config_from_schema(
            schema.detector_adversarial, DetectorAdversarialConfig
        ),
        classification=_classification_from_schema(schema.classification),
        adversarial=_adversarial_from_schema(schema.adversarial),
        analyst=_analyst_from_schema(schema.analyst),
        executor=_executor_from_schema(schema.executor),
        taxonomies=[Taxonomy(**t.model_dump()) for t in schema.taxonomies],
        modus_operandi=[ModusOperandi(**m.model_dump()) for m in schema.modus_operandi],
        flags=[_flag_from_schema(f) for f in schema.flags],
        example_cases=[ExampleCase(**e.model_dump()) for e in schema.example_cases],
        active_fields=schema.active_fields,
        active_model_id=schema.active_model_id,
    )


def _test_from_schema(schema: TestSettingsSchema) -> TestSettings:
    return TestSettings(**schema.model_dump())


def _filter_condition_from_schema(schema: FilterConditionSchema) -> FilterCondition:
    return FilterCondition(
        id=schema.id,
        category=schema.category,
        operator=schema.operator,
        values=schema.values,
    )


def _filter_group_from_schema(schema: FilterGroupSchema) -> FilterGroup:
    return FilterGroup(
        id=schema.id,
        operator=schema.operator,
        conditions=[_filter_condition_from_schema(c) for c in schema.conditions],
        groups=[_filter_group_from_schema(g) for g in schema.groups],
    )


def _segment_settings_from_schema(schema: SegmentSettingsSchema) -> SegmentSettings:
    return SegmentSettings(
        enabled=schema.enabled,
        filter=_filter_group_from_schema(schema.filter),
        monitoring=_monitoring_from_schema(schema.monitoring),
        agent=_agent_from_schema(schema.agent),
        order=schema.order,
    )


def _filter_condition_to_schema(condition: FilterCondition) -> FilterConditionSchema:
    return FilterConditionSchema(
        id=condition.id,
        category=condition.category,
        operator=condition.operator,
        values=condition.values,
    )


def _filter_group_to_schema(group: FilterGroup) -> FilterGroupSchema:
    return FilterGroupSchema(
        id=group.id,
        operator=group.operator,
        conditions=[_filter_condition_to_schema(c) for c in group.conditions],
        groups=[_filter_group_to_schema(g) for g in group.groups],
    )


def _segment_settings_to_schema(settings: SegmentSettings) -> SegmentSettingsSchema:
    return SegmentSettingsSchema(
        enabled=settings.enabled,
        filter=_filter_group_to_schema(settings.filter),
        monitoring=_monitoring_to_schema(settings.monitoring),
        agent=_agent_to_schema(settings.agent),
        order=settings.order,
    )
