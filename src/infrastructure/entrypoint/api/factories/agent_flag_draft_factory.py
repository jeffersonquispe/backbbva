from src.application.ports.vector_store_instance_port import KnowledgeAssetType
from src.application.use_cases.agent.draft_flag import (
    ConfirmFlagDraftUseCase,
    GenerateFlagDraftUseCase,
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
from src.infrastructure.agents.llm_structured_agent_generator import (
    LLMStructuredAgentGenerator,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_assistant_optimizer_settings_repository,
)
from src.infrastructure.entrypoint.api.factories.flag_library_factory import (
    get_create_flag_library_entry_use_case,
    get_flag_library_repository,
    get_update_flag_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.factories.modus_operandi_library_factory import (
    get_modus_operandi_library_repository,
)
from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import (
    get_knowledge_graph_service,
)
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)


def _generator() -> LLMStructuredAgentGenerator:
    return LLMStructuredAgentGenerator(
        llm_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=genai_config.REPORT_LLM_MODEL or genai_config.EXECUTOR_LLM_MODEL,
    )


def _sync_new_asset(flag_type, entry_id: str) -> None:
    asset_type = (
        KnowledgeAssetType.RED_FLAG
        if flag_type.value == "red"
        else KnowledgeAssetType.YELLOW_FLAG
    )
    get_knowledge_graph_service().synchronize_new_asset(asset_type, entry_id)


def get_generate_flag_draft_use_case() -> GenerateFlagDraftUseCase:
    return GenerateFlagDraftUseCase(
        sessions=get_agent_session_repository(),
        messages=get_agent_message_repository(),
        prompts=get_agent_prompt_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        entries=get_flag_library_repository(),
        modus_operandi=get_modus_operandi_library_repository(),
        settings=get_assistant_optimizer_settings_repository(),
        generator=_generator(),
        masker=get_personal_data_masker(),
        clock=get_clock(),
        ids=get_id_generator(),
    )


def get_confirm_flag_draft_use_case() -> ConfirmFlagDraftUseCase:
    return ConfirmFlagDraftUseCase(
        sessions=get_agent_session_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        confirmations=get_agent_confirmation_repository(),
        entries=get_flag_library_repository(),
        modus_operandi=get_modus_operandi_library_repository(),
        create_entry=get_create_flag_library_entry_use_case(),
        update_entry=get_update_flag_library_entry_use_case(),
        synchronize_new_asset=_sync_new_asset,
        audit=get_audit_repository(),
        clock=get_clock(),
        ids=get_id_generator(),
    )
