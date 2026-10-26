from src.application.use_cases.agent.draft_watchlist import (
    ConfirmWatchlistDraftUseCase,
    GenerateWatchlistDraftUseCase,
)
from src.infrastructure.agents.factories import (
    get_agent_confirmation_repository,
    get_agent_message_repository,
    get_agent_package_repository,
    get_agent_prompt_repository,
    get_agent_session_repository,
    get_agent_timeline,
    get_agent_verification_repository,
    get_personal_data_masker,
)
from src.infrastructure.agents.llm_structured_agent_generator import (
    LLMStructuredAgentGenerator,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_assistant_optimizer_settings_repository,
)
from src.infrastructure.entrypoint.api.factories.watchlist_factory import (
    get_create_watchlist_use_case,
    get_update_watchlist_use_case,
)
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.watchlist_repository import (
    DynamoWatchlistRepository,
)


def _generator() -> LLMStructuredAgentGenerator:
    return LLMStructuredAgentGenerator(
        llm_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=genai_config.REPORT_LLM_MODEL or genai_config.EXECUTOR_LLM_MODEL,
    )


def get_generate_watchlist_draft_use_case() -> GenerateWatchlistDraftUseCase:
    return GenerateWatchlistDraftUseCase(
        sessions=get_agent_session_repository(),
        messages=get_agent_message_repository(),
        prompts=get_agent_prompt_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        entries=DynamoWatchlistRepository(),
        settings=get_assistant_optimizer_settings_repository(),
        generator=_generator(),
        masker=get_personal_data_masker(),
        clock=get_clock(),
        ids=get_id_generator(),
    )


def get_confirm_watchlist_draft_use_case() -> ConfirmWatchlistDraftUseCase:
    return ConfirmWatchlistDraftUseCase(
        sessions=get_agent_session_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        confirmations=get_agent_confirmation_repository(),
        entries=DynamoWatchlistRepository(),
        create_entry=get_create_watchlist_use_case(),
        update_entry=get_update_watchlist_use_case(),
        audit=get_audit_repository(),
        timeline=get_agent_timeline(),
        clock=get_clock(),
        ids=get_id_generator(),
    )
