from src.application.use_cases.agent.draft_modus_operandi import (
    ConfirmModusOperandiDraftUseCase,
    GenerateModusOperandiDraftUseCase,
)
from src.infrastructure.agents.factories import (
    get_agent_confirmation_repository,
    get_agent_message_repository,
    get_agent_package_repository,
    get_agent_prompt_repository,
    get_agent_session_repository,
    get_agent_verification_repository,
    get_modus_operandi_generator_subagent,
    get_personal_data_masker,
)
from src.infrastructure.agents.modus_operandi_draft_applier import (
    ExistingModusOperandiUseCasesApplier,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.assistant_optimizer_settings_factory import (
    get_assistant_optimizer_settings_repository,
)
from src.infrastructure.entrypoint.api.factories.modus_operandi_library_factory import (
    get_create_modus_operandi_library_entry_use_case,
    get_modus_operandi_library_repository,
    get_update_modus_operandi_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.factories.taxonomy_library_factory import (
    get_taxonomy_library_repository,
)
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)


def get_generate_modus_operandi_draft_use_case() -> GenerateModusOperandiDraftUseCase:
    return GenerateModusOperandiDraftUseCase(
        sessions=get_agent_session_repository(),
        messages=get_agent_message_repository(),
        prompts=get_agent_prompt_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        entries=get_modus_operandi_library_repository(),
        taxonomies=get_taxonomy_library_repository(),
        settings=get_assistant_optimizer_settings_repository(),
        subagent=get_modus_operandi_generator_subagent(),
        masker=get_personal_data_masker(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_confirm_modus_operandi_draft_use_case() -> ConfirmModusOperandiDraftUseCase:
    return ConfirmModusOperandiDraftUseCase(
        sessions=get_agent_session_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        confirmations=get_agent_confirmation_repository(),
        entries=get_modus_operandi_library_repository(),
        applier=ExistingModusOperandiUseCasesApplier(
            create=get_create_modus_operandi_library_entry_use_case(),
            update=get_update_modus_operandi_library_entry_use_case(),
        ),
        audit=get_audit_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )
