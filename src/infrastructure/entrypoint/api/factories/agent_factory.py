from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.use_cases.agent.chat_with_agent import ChatWithAgentUseCase
from src.application.use_cases.agent.create_agent_session import (
    CreateAgentSessionUseCase,
)
from src.application.use_cases.agent.manage_agent_entity_claims import (
    AgentEntityClaimUseCase,
)
from src.application.use_cases.agent.manage_agent_insight import (
    ManageAgentInsightUseCase,
)
from src.application.use_cases.agent.manage_agent_session import (
    ManageAgentSessionUseCase,
)
from src.application.use_cases.agent.renew_agent_budget import RenewAgentBudgetUseCase
from src.application.use_cases.agent.retrieve_project_context import (
    RetrieveProjectContextUseCase,
)
from src.infrastructure.agents.factories import (
    get_agent_audit_repository,
    get_agent_budget_ledger_repository,
    get_agent_chat_responder,
    get_agent_entity_claim_repository,
    get_agent_experiment_component_resolver,
    get_agent_insight_repository,
    get_agent_link_repository,
    get_agent_message_repository,
    get_agent_objective_repository,
    get_agent_prompt_repository,
    get_agent_session_repository,
    get_agent_session_summary_repository,
    get_personal_data_masker,
    get_project_graph_repository,
    get_project_graph_semantic_search,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_assistant_optimizer_settings_repository,
)


def get_assistant_optimizer_settings_port() -> AssistantOptimizerSettingsPort:
    return get_assistant_optimizer_settings_repository()


def get_create_agent_session_use_case(
    settings: AssistantOptimizerSettingsPort,
) -> CreateAgentSessionUseCase:
    return CreateAgentSessionUseCase(
        sessions=get_agent_session_repository(),
        prompts=get_agent_prompt_repository(),
        objectives=get_agent_objective_repository(),
        components=get_agent_experiment_component_resolver(),
        settings=settings,
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_manage_agent_session_use_case(
    settings: AssistantOptimizerSettingsPort | None = None,
) -> ManageAgentSessionUseCase:
    return ManageAgentSessionUseCase(
        repository=get_agent_session_repository(),
        clock=get_clock(),
        settings=settings,
        audit=get_agent_audit_repository(),
    )


def get_chat_with_agent_use_case() -> ChatWithAgentUseCase:
    return ChatWithAgentUseCase(
        sessions=get_agent_session_repository(),
        messages=get_agent_message_repository(),
        insights=get_agent_insight_repository(),
        links=get_agent_link_repository(),
        summaries=get_agent_session_summary_repository(),
        prompts=get_agent_prompt_repository(),
        settings=get_assistant_optimizer_settings_repository(),
        masker=get_personal_data_masker(),
        responder=get_agent_chat_responder(),
        clock=get_clock(),
        id_generator=get_id_generator(),
        project_context=RetrieveProjectContextUseCase(
            graph=get_project_graph_repository(),
            semantic=get_project_graph_semantic_search(),
        ),
    )


def get_manage_agent_insight_use_case() -> ManageAgentInsightUseCase:
    return ManageAgentInsightUseCase(
        sessions=get_agent_session_repository(),
        insights=get_agent_insight_repository(),
        clock=get_clock(),
    )


def get_agent_entity_claim_use_case() -> AgentEntityClaimUseCase:
    return AgentEntityClaimUseCase(
        sessions=get_agent_session_repository(),
        claims=get_agent_entity_claim_repository(),
        clock=get_clock(),
    )


def get_renew_agent_budget_use_case() -> RenewAgentBudgetUseCase:
    return RenewAgentBudgetUseCase(
        sessions=get_agent_session_repository(),
        ledger=get_agent_budget_ledger_repository(),
        settings=get_assistant_optimizer_settings_repository(),
        clock=get_clock(),
        ids=get_id_generator(),
    )
