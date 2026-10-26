from src.application.ports.agent_release_port import AgentReleaseRepository
from src.application.use_cases.agent.manage_agent_release import (
    ManageAgentReleaseUseCase,
)
from src.application.use_cases.agent.paired_agent_experiment_runner import (
    PairedAgentExperimentRunner,
)
from src.application.use_cases.agent.validate_retrospective_release import (
    ValidateRetrospectiveReleaseUseCase,
)
from src.infrastructure.agents.factories import (
    get_agent_audit_repository,
    get_agent_experiment_component_resolver,
    get_agent_experiment_repository,
    get_agent_timeline,
)
from src.infrastructure.agents.factories import (
    get_agent_release_repository as get_dynamo_agent_release_repository,
)
from src.infrastructure.agents.mcp_resolved_agent_pipeline_scorer import (
    MCPResolvedAgentPipelineScorer,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.agent_objective_factory import (
    get_agent_objective_repository,
)
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_dataset_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.mature_sample_repository import (
    DynamoDatasetSnapshotRepository,
)


def get_validate_retrospective_release_use_case() -> ValidateRetrospectiveReleaseUseCase:
    return ValidateRetrospectiveReleaseUseCase(
        experiments=get_agent_experiment_repository(),
        releases=get_dynamo_agent_release_repository(),
        snapshots=DynamoDatasetSnapshotRepository(),
        datasets=get_dataset_repository(),
        objectives=get_agent_objective_repository(),
        evaluator=PairedAgentExperimentRunner(
            components=get_agent_experiment_component_resolver(),
            scorer=MCPResolvedAgentPipelineScorer(),
            objectives=get_agent_objective_repository(),
        ),
        audit=get_agent_audit_repository(),
        now=get_clock().now,
        new_id=lambda: str(get_id_generator().new_id()),
    )


def get_manage_agent_release_use_case() -> ManageAgentReleaseUseCase:
    return ManageAgentReleaseUseCase(
        releases=get_dynamo_agent_release_repository(),
        components=get_agent_experiment_component_resolver(),
        audit=get_agent_audit_repository(),
        now=get_clock().now,
        new_id=lambda: str(get_id_generator().new_id()),
        timeline=get_agent_timeline(),
    )


def get_agent_release_repository() -> AgentReleaseRepository:
    return get_dynamo_agent_release_repository()
