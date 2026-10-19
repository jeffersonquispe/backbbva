from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.use_cases.agent.create_agent_session import (
    CreateAgentSessionUseCase,
)
from src.application.use_cases.agent.manage_agent_session import (
    ManageAgentSessionUseCase,
)
from src.infrastructure.agents.factories import (
    get_agent_prompt_repository,
    get_agent_session_repository,
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
    )
