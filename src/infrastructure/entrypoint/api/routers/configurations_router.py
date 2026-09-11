from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.ports.configuration_port import (
    AdversarialConfig,
    AgentSettings,
    AnalystCapacity,
    AnalystConfig,
    AnalystPlaybook,
    ClassificationConfig,
    ConfigurationRecord,
    DayProfile,
    DistributionValue,
    DocumentationConfig,
    ExampleCase,
    FilterCondition,
    FilterGroup,
    Flag,
    GeneralSettings,
    InfraSettings,
    ModusOperandi,
    MonitoringSettings,
    OpsSettings,
    ProfilingConfig,
    ProfilingStrategy,
    SamplingCriterion,
    SegmentSettings,
    ShortageBehavior,
    Taxonomy,
    TestSettings,
    VoicebotCategoryPrompt,
    VoicebotConfig,
)
from src.application.use_cases.configurations.activate_configuration import (
    ActivateConfigurationUseCase,
    ConfigurationNotFoundError,
    ConfigurationNotTestedError,
)
from src.application.use_cases.configurations.create_configuration import (
    ConfigurationVersionConflictError,
    CreateConfigurationUseCase,
)
from src.application.use_cases.configurations.get_active_configuration import (
    GetActiveConfigurationUseCase,
)
from src.application.use_cases.configurations.get_configuration import (
    GetConfigurationUseCase,
)
from src.application.use_cases.configurations.list_configuration_versions import (
    ListConfigurationVersionsUseCase,
)
from src.application.use_cases.configurations.list_configurations import (
    ListConfigurationsUseCase,
)
from src.application.use_cases.configurations.test_configuration import (
    ConfigurationBaseNotFoundError,
    PreviewConfigurationUseCase,
)
from src.infrastructure.entrypoint.api.factories.configuration_factory import (
    get_activate_configuration_use_case,
    get_create_configuration_use_case,
    get_get_active_configuration_use_case,
    get_get_configuration_use_case,
    get_list_configuration_versions_use_case,
    get_list_configurations_use_case,
    get_test_configuration_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    AdversarialConfigSchema,
    AgentSettingsSchema,
    AnalystCapacitySchema,
    AnalystConfigSchema,
    AnalystPlaybookSchema,
    ClassificationConfigSchema,
    ConfigurationChangeResponse,
    ConfigurationDetailResponse,
    ConfigurationSummaryResponse,
    CreateConfigurationRequest,
    DayProfileSchema,
    DistributionValueSchema,
    DocumentationConfigSchema,
    ExampleCaseSchema,
    FilterConditionSchema,
    FilterGroupSchema,
    FlagSchema,
    GeneralSettingsSchema,
    InfraSettingsSchema,
    ModusOperandiSchema,
    MonitoringSettingsSchema,
    OpsSettingsSchema,
    ProfilingConfigSchema,
    ProfilingStrategySchema,
    SamplingCriterionSchema,
    SegmentSettingsSchema,
    ShortageBehaviorSchema,
    TaxonomySchema,
    TestConfigurationResponse,
    TestSettingsSchema,
    VoicebotCategoryPromptSchema,
    VoicebotConfigSchema,
)

router = APIRouter(prefix="/configurations", tags=["configurations"])
configuration_test_router = APIRouter(
    prefix="/configuration", tags=["configurations"]
)


@configuration_test_router.post("/test", response_model=TestConfigurationResponse)
def test_configuration(
    request: CreateConfigurationRequest,
    use_case: Annotated[
        PreviewConfigurationUseCase, Depends(get_test_configuration_use_case)
    ],
):
    try:
        result = use_case.execute(_input_from_request(request))
    except ConfigurationVersionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ConfigurationBaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TestConfigurationResponse(
        valid=result.valid,
        changes=[
            ConfigurationChangeResponse(**change.__dict__) for change in result.changes
        ],
        warnings=result.warnings,
    )


@router.post("", response_model=ConfigurationDetailResponse, status_code=status.HTTP_201_CREATED)
def create_configuration(
    request: CreateConfigurationRequest,
    use_case: Annotated[
        CreateConfigurationUseCase, Depends(get_create_configuration_use_case)
    ],
):
    try:
        record = use_case.execute(_input_from_request(request))
    except ConfigurationVersionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_detail_response(record)


def _input_from_request(request: CreateConfigurationRequest) -> CreateConfigurationInput:
    return CreateConfigurationInput(
        name=request.name,
        configuration_id=request.configuration_id,
        based_on_version=request.based_on_version,
        description=request.description,
        general=_general_from_schema(request.general),
        infra=_infra_from_schema(request.infra),
        ops=_ops_from_schema(request.ops),
        test=_test_from_schema(request.test),
        created_by=request.created_by,
        segments={
            code: _segment_settings_from_schema(schema)
            for code, schema in request.segments.items()
        },
    )


@router.get("", response_model=list[ConfigurationSummaryResponse])
def list_configurations(
    use_case: Annotated[
        ListConfigurationsUseCase, Depends(get_list_configurations_use_case)
    ],
):
    return [_to_summary_response(record) for record in use_case.execute()]


@router.get("/active", response_model=ConfigurationDetailResponse)
def get_active_configuration(
    use_case: Annotated[
        GetActiveConfigurationUseCase, Depends(get_get_active_configuration_use_case)
    ],
):
    record = use_case.execute()
    if record is None:
        raise HTTPException(status_code=404, detail="No active configuration")
    return _to_detail_response(record)


@router.get("/{configuration_id}", response_model=list[ConfigurationSummaryResponse])
def list_configuration_versions(
    configuration_id: str,
    use_case: Annotated[
        ListConfigurationVersionsUseCase,
        Depends(get_list_configuration_versions_use_case),
    ],
):
    records = use_case.execute(configuration_id)
    if not records:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return [_to_summary_response(record) for record in records]


@router.get(
    "/{configuration_id}/versions/{version}",
    response_model=ConfigurationDetailResponse,
)
def get_configuration(
    configuration_id: str,
    version: int,
    use_case: Annotated[
        GetConfigurationUseCase, Depends(get_get_configuration_use_case)
    ],
):
    record = use_case.execute(configuration_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return _to_detail_response(record)


@router.post(
    "/{configuration_id}/versions/{version}/activate",
    response_model=ConfigurationDetailResponse,
)
def activate_configuration(
    configuration_id: str,
    version: int,
    use_case: Annotated[
        ActivateConfigurationUseCase, Depends(get_activate_configuration_use_case)
    ],
):
    try:
        record = use_case.execute(configuration_id, version)
    except ConfigurationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigurationNotTestedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_detail_response(record)


def _to_summary_response(record: ConfigurationRecord) -> ConfigurationSummaryResponse:
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
    )


def _to_detail_response(record: ConfigurationRecord) -> ConfigurationDetailResponse:
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
        created_by=record.created_by,
        general=GeneralSettingsSchema(**record.general.__dict__),
        infra=InfraSettingsSchema(**record.infra.__dict__),
        ops=OpsSettingsSchema(
            voicebot_max_concurrent_calls=record.ops.voicebot_max_concurrent_calls,
            analyst_capacity=AnalystCapacitySchema(
                profiles=[
                    DayProfileSchema(**p.__dict__)
                    for p in record.ops.analyst_capacity.profiles
                ],
                default_profile_id=record.ops.analyst_capacity.default_profile_id,
                day_overrides=record.ops.analyst_capacity.day_overrides,
            ),
            queue_max_lifetime_value=record.ops.queue_max_lifetime_value,
            queue_max_lifetime_unit=record.ops.queue_max_lifetime_unit,
            queue_discard_amount_threshold=record.ops.queue_discard_amount_threshold,
            queue_rule_filter_enabled=record.ops.queue_rule_filter_enabled,
            queue_rule_filter_mode=record.ops.queue_rule_filter_mode,
            queue_allowed_triggered_rules=record.ops.queue_allowed_triggered_rules,
            queue_discard_behavior=ShortageBehaviorSchema(
                **record.ops.queue_discard_behavior.__dict__
            ),
            voicebot_shortage_behavior=ShortageBehaviorSchema(
                **record.ops.voicebot_shortage_behavior.__dict__
            ),
            analyst_shortage_behavior=ShortageBehaviorSchema(
                **record.ops.analyst_shortage_behavior.__dict__
            ),
        ),
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


def _classification_to_schema(
    classification: ClassificationConfig,
) -> ClassificationConfigSchema:
    return ClassificationConfigSchema(**classification.__dict__)


def _adversarial_to_schema(adversarial: AdversarialConfig) -> AdversarialConfigSchema:
    return AdversarialConfigSchema(**adversarial.__dict__)


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
        playbooks=[AnalystPlaybookSchema(**p.__dict__) for p in analyst.playbooks],
        voicebot=_voicebot_to_schema(analyst.voicebot),
    )


def _documentation_to_schema(
    documentation: DocumentationConfig,
) -> DocumentationConfigSchema:
    return DocumentationConfigSchema(**documentation.__dict__)


def _agent_to_schema(agent: AgentSettings) -> AgentSettingsSchema:
    return AgentSettingsSchema(
        profiling=_profiling_to_schema(agent.profiling),
        classification=_classification_to_schema(agent.classification),
        adversarial=_adversarial_to_schema(agent.adversarial),
        analyst=_analyst_to_schema(agent.analyst),
        documentation=_documentation_to_schema(agent.documentation),
        taxonomies=[TaxonomySchema(**t.__dict__) for t in agent.taxonomies],
        modus_operandi=[
            ModusOperandiSchema(**m.__dict__) for m in agent.modus_operandi
        ],
        flags=[_flag_to_schema(f) for f in agent.flags],
        example_cases=[
            ExampleCaseSchema(**e.__dict__) for e in agent.example_cases
        ],
        active_fields=agent.active_fields,
        active_model_id=agent.active_model_id,
    )


def _general_from_schema(schema: GeneralSettingsSchema) -> GeneralSettings:
    return GeneralSettings(**schema.model_dump())


def _infra_from_schema(schema: InfraSettingsSchema) -> InfraSettings:
    return InfraSettings(**schema.model_dump())


def _ops_from_schema(schema: OpsSettingsSchema) -> OpsSettings:
    return OpsSettings(
        voicebot_max_concurrent_calls=schema.voicebot_max_concurrent_calls,
        analyst_capacity=AnalystCapacity(
            profiles=[
                DayProfile(**p.model_dump())
                for p in schema.analyst_capacity.profiles
            ],
            default_profile_id=schema.analyst_capacity.default_profile_id,
            day_overrides=schema.analyst_capacity.day_overrides,
        ),
        queue_max_lifetime_value=schema.queue_max_lifetime_value,
        queue_max_lifetime_unit=schema.queue_max_lifetime_unit,
        queue_discard_amount_threshold=schema.queue_discard_amount_threshold,
        queue_rule_filter_enabled=schema.queue_rule_filter_enabled,
        queue_rule_filter_mode=schema.queue_rule_filter_mode,
        queue_allowed_triggered_rules=schema.queue_allowed_triggered_rules,
        queue_discard_behavior=ShortageBehavior(
            **schema.queue_discard_behavior.model_dump()
        ),
        voicebot_shortage_behavior=ShortageBehavior(
            **schema.voicebot_shortage_behavior.model_dump()
        ),
        analyst_shortage_behavior=ShortageBehavior(
            **schema.analyst_shortage_behavior.model_dump()
        ),
    )


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
        strategies=[
            ProfilingStrategy(**s.model_dump()) for s in schema.strategies
        ],
    )


def _classification_from_schema(
    schema: ClassificationConfigSchema,
) -> ClassificationConfig:
    return ClassificationConfig(**schema.model_dump())


def _adversarial_from_schema(schema: AdversarialConfigSchema) -> AdversarialConfig:
    return AdversarialConfig(**schema.model_dump())


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
        playbooks=[AnalystPlaybook(**p.model_dump()) for p in schema.playbooks],
        voicebot=_voicebot_from_schema(schema.voicebot),
    )


def _documentation_from_schema(
    schema: DocumentationConfigSchema,
) -> DocumentationConfig:
    return DocumentationConfig(**schema.model_dump())


def _agent_from_schema(schema: AgentSettingsSchema) -> AgentSettings:
    return AgentSettings(
        profiling=_profiling_from_schema(schema.profiling),
        classification=_classification_from_schema(schema.classification),
        adversarial=_adversarial_from_schema(schema.adversarial),
        analyst=_analyst_from_schema(schema.analyst),
        documentation=_documentation_from_schema(schema.documentation),
        taxonomies=[Taxonomy(**t.model_dump()) for t in schema.taxonomies],
        modus_operandi=[
            ModusOperandi(**m.model_dump()) for m in schema.modus_operandi
        ],
        flags=[_flag_from_schema(f) for f in schema.flags],
        example_cases=[
            ExampleCase(**e.model_dump()) for e in schema.example_cases
        ],
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
