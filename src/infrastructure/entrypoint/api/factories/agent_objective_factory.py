from functools import lru_cache

from src.application.use_cases.agent.evaluate_global_pipeline import (
    StartGlobalPipelineEvaluation,
)
from src.application.use_cases.agent.manage_agent_objective import (
    GLOBAL_FRAUD_OBJECTIVE_ID,
    ActivateAgentObjectiveVersion,
    CreateAgentObjectiveVersion,
)
from src.infrastructure.agents.factories import get_agent_verification_repository
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_assistant_optimizer_settings_repository,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_operational_settings_repository,
)
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_objective_repository import (
    DynamoAgentObjectiveRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.mature_sample_repository import (
    DynamoDatasetSnapshotRepository,
    DynamoMatureSamplerSchemaMappingRepository,
)
from src.infrastructure.queues.celery.global_pipeline_evaluation_dispatcher import (
    CeleryGlobalPipelineEvaluationDispatcher,
)
from src.infrastructure.workflows.celery.factories import get_model_repository


@lru_cache(maxsize=1)
def get_agent_objective_repository() -> DynamoAgentObjectiveRepository:
    return DynamoAgentObjectiveRepository()


def get_create_agent_objective_version() -> CreateAgentObjectiveVersion:
    return CreateAgentObjectiveVersion(
        objectives=get_agent_objective_repository(),
        optimizer_settings=get_assistant_optimizer_settings_repository(),
        operational_settings=get_operational_settings_repository(),
        schema_mapping=DynamoMatureSamplerSchemaMappingRepository(),
        clock=get_clock(),
    )


def get_activate_agent_objective_version() -> ActivateAgentObjectiveVersion:
    return ActivateAgentObjectiveVersion(
        objectives=get_agent_objective_repository(),
        audit=get_audit_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def list_agent_objective_versions():
    return get_agent_objective_repository().list_versions(GLOBAL_FRAUD_OBJECTIVE_ID)


def get_start_global_pipeline_evaluation() -> StartGlobalPipelineEvaluation:
    return StartGlobalPipelineEvaluation(
        snapshots=DynamoDatasetSnapshotRepository(),
        models=get_model_repository(),
        objectives=get_agent_objective_repository(),
        verifications=get_agent_verification_repository(),
        dispatcher=CeleryGlobalPipelineEvaluationDispatcher(),
        clock=get_clock(),
    )
