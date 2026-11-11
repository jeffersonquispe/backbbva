from functools import lru_cache

from src.application.use_cases.agent.draft_resource import (
    ConfirmResourceDraftUseCase,
    GenerateResourceDraftUseCase,
)
from src.infrastructure.agents.agent_draft_resource_adapter import (
    AgentDraftResourceAdapter,
)
from src.infrastructure.agents.factories import (
    get_agent_confirmation_repository,
    get_agent_message_repository,
    get_agent_package_repository,
    get_agent_prompt_repository,
    get_agent_session_repository,
    get_agent_verification_repository,
    get_personal_data_masker,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_assistant_optimizer_settings_repository,
)
from src.infrastructure.entrypoint.api.factories.channel_library_factory import (
    get_channel_library_repository,
    get_create_channel_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_create_empty_dataset_use_case,
    get_list_datasets_use_case,
)
from src.infrastructure.entrypoint.api.factories.tag_catalog_factory import (
    get_create_tag_use_case,
    get_tag_catalog_repository,
)
from src.infrastructure.llm.catalog.element_llm import get_element_llm_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)


@lru_cache
def get_agent_draft_resource_adapter() -> AgentDraftResourceAdapter:
    return AgentDraftResourceAdapter(
        channels=get_channel_library_repository(),
        tags=get_tag_catalog_repository(),
        datasets=get_list_datasets_use_case(),
        create_channel=get_create_channel_library_entry_use_case(),
        create_tag=get_create_tag_use_case(),
        create_dataset=get_create_empty_dataset_use_case(),
    )


def _generator():
    from src.infrastructure.agents.llm_structured_agent_generator import (
        LLMStructuredAgentGenerator,
    )

    return LLMStructuredAgentGenerator(
        llm_factory=get_element_llm_factory("agent_drafts"),
        monitoring=get_monitoring(),
        model=genai_config.REPORT_LLM_MODEL or genai_config.EXECUTOR_LLM_MODEL,
    )


def get_generate_resource_draft_use_case() -> GenerateResourceDraftUseCase:
    return GenerateResourceDraftUseCase(
        sessions=get_agent_session_repository(),
        messages=get_agent_message_repository(),
        prompts=get_agent_prompt_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        resources=get_agent_draft_resource_adapter(),
        settings=get_assistant_optimizer_settings_repository(),
        generator=_generator(),
        masker=get_personal_data_masker(),
        clock=get_clock(),
        ids=get_id_generator(),
    )


def get_confirm_resource_draft_use_case() -> ConfirmResourceDraftUseCase:
    return ConfirmResourceDraftUseCase(
        sessions=get_agent_session_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        confirmations=get_agent_confirmation_repository(),
        resources=get_agent_draft_resource_adapter(),
        audit=get_audit_repository(),
        clock=get_clock(),
        ids=get_id_generator(),
    )
