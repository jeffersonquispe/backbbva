from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.ports.configuration_port import (
    AgentSettings,
    AnalystCapacity,
    ConfigurationRecord,
    DayProfile,
    DistributionValue,
    ExampleCase,
    GeneralSettings,
    InfraSettings,
    ModusOperandi,
    MonitoringSettings,
    OpsSettings,
    RedFlag,
    SamplingCriterion,
    ShortageBehavior,
    Taxonomy,
    TestSettings,
    YellowFlag,
)
from src.application.use_cases.configurations.activate_configuration import (
    ActivateConfigurationUseCase,
    ConfigurationNotFoundError,
)
from src.application.use_cases.configurations.create_configuration import (
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
from src.infrastructure.entrypoint.api.factories.configuration_factory import (
    get_activate_configuration_use_case,
    get_create_configuration_use_case,
    get_get_active_configuration_use_case,
    get_get_configuration_use_case,
    get_list_configuration_versions_use_case,
    get_list_configurations_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    AgentSettingsSchema,
    AnalystCapacitySchema,
    ConfigurationDetailResponse,
    ConfigurationSummaryResponse,
    CreateConfigurationRequest,
    DayProfileSchema,
    DistributionValueSchema,
    ExampleCaseSchema,
    GeneralSettingsSchema,
    InfraSettingsSchema,
    ModusOperandiSchema,
    MonitoringSettingsSchema,
    OpsSettingsSchema,
    RedFlagSchema,
    SamplingCriterionSchema,
    ShortageBehaviorSchema,
    TaxonomySchema,
    TestSettingsSchema,
    YellowFlagSchema,
)

router = APIRouter(prefix="/configurations", tags=["configurations"])


@router.post("", response_model=ConfigurationDetailResponse, status_code=status.HTTP_201_CREATED)
def create_configuration(
    request: CreateConfigurationRequest,
    use_case: Annotated[
        CreateConfigurationUseCase, Depends(get_create_configuration_use_case)
    ],
):
    record = use_case.execute(
        CreateConfigurationInput(
            name=request.name,
            configuration_id=request.configuration_id,
            description=request.description,
            general=_general_from_schema(request.general),
            infra=_infra_from_schema(request.infra),
            ops=_ops_from_schema(request.ops),
            monitoring=_monitoring_from_schema(request.monitoring),
            agent=_agent_from_schema(request.agent),
            test=_test_from_schema(request.test),
            created_by=request.created_by,
        )
    )
    return _to_detail_response(record)


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
    return _to_detail_response(record)


def _to_summary_response(record: ConfigurationRecord) -> ConfigurationSummaryResponse:
    return ConfigurationSummaryResponse(
        configuration_id=record.configuration_id,
        version=record.version,
        name=record.name,
        description=record.description,
        active=record.active,
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
            voicebot_shortage_behavior=ShortageBehaviorSchema(
                **record.ops.voicebot_shortage_behavior.__dict__
            ),
            analyst_shortage_behavior=ShortageBehaviorSchema(
                **record.ops.analyst_shortage_behavior.__dict__
            ),
        ),
        monitoring=MonitoringSettingsSchema(
            sampling_interval_value=record.monitoring.sampling_interval_value,
            sampling_interval_unit=record.monitoring.sampling_interval_unit,
            sampling_criteria=[
                SamplingCriterionSchema(
                    id=c.id,
                    name=c.name,
                    values=[
                        DistributionValueSchema(**v.__dict__) for v in c.values
                    ],
                )
                for c in record.monitoring.sampling_criteria
            ],
            max_samples=record.monitoring.max_samples,
            prompt_clasificacion=record.monitoring.prompt_clasificacion,
            prompt_analista=record.monitoring.prompt_analista,
            prompt_monitoreo=record.monitoring.prompt_monitoreo,
            evaluation_variables=record.monitoring.evaluation_variables,
        ),
        agent=AgentSettingsSchema(
            perfil_usuario=record.agent.perfil_usuario,
            perfil_usuario_vars=record.agent.perfil_usuario_vars,
            perfil_transaccion=record.agent.perfil_transaccion,
            perfil_transaccion_vars=record.agent.perfil_transaccion_vars,
            perfil_transaccional=record.agent.perfil_transaccional,
            perfil_transaccional_vars=record.agent.perfil_transaccional_vars,
            taxonomies=[
                TaxonomySchema(**t.__dict__) for t in record.agent.taxonomies
            ],
            modus_operandi=[
                ModusOperandiSchema(**m.__dict__)
                for m in record.agent.modus_operandi
            ],
            red_flags=[RedFlagSchema(**r.__dict__) for r in record.agent.red_flags],
            yellow_flags=[
                YellowFlagSchema(**y.__dict__) for y in record.agent.yellow_flags
            ],
            example_cases=[
                ExampleCaseSchema(**e.__dict__) for e in record.agent.example_cases
            ],
            active_fields=record.agent.active_fields,
        ),
        test=TestSettingsSchema(**record.test.__dict__),
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
        prompt_analista=schema.prompt_analista,
        prompt_monitoreo=schema.prompt_monitoreo,
        evaluation_variables=schema.evaluation_variables,
    )


def _agent_from_schema(schema: AgentSettingsSchema) -> AgentSettings:
    return AgentSettings(
        perfil_usuario=schema.perfil_usuario,
        perfil_usuario_vars=schema.perfil_usuario_vars,
        perfil_transaccion=schema.perfil_transaccion,
        perfil_transaccion_vars=schema.perfil_transaccion_vars,
        perfil_transaccional=schema.perfil_transaccional,
        perfil_transaccional_vars=schema.perfil_transaccional_vars,
        taxonomies=[Taxonomy(**t.model_dump()) for t in schema.taxonomies],
        modus_operandi=[
            ModusOperandi(**m.model_dump()) for m in schema.modus_operandi
        ],
        red_flags=[RedFlag(**r.model_dump()) for r in schema.red_flags],
        yellow_flags=[YellowFlag(**y.model_dump()) for y in schema.yellow_flags],
        example_cases=[
            ExampleCase(**e.model_dump()) for e in schema.example_cases
        ],
        active_fields=schema.active_fields,
    )


def _test_from_schema(schema: TestSettingsSchema) -> TestSettings:
    return TestSettings(**schema.model_dump())
