from __future__ import annotations

from functools import lru_cache

from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetLedgerRepository,
)
from src.application.ports.agent_chat_responder_port import AgentChatResponder
from src.application.ports.agent_confirmation_port import (
    AgentConfirmationRepository,
)
from src.application.ports.agent_insight_port import AgentInsightRepository
from src.application.ports.agent_iteration_port import AgentIterationRepository
from src.application.ports.agent_link_port import AgentLinkRepository
from src.application.ports.agent_message_port import AgentMessageRepository
from src.application.ports.agent_package_port import AgentPackageRepository
from src.application.ports.agent_prompt_port import AgentPromptRepository
from src.application.ports.agent_run_port import AgentRunRepository
from src.application.ports.agent_session_port import AgentSessionRepository
from src.application.ports.agent_session_summary_port import (
    AgentSessionSummaryRepository,
)
from src.application.ports.agent_tool_call_port import AgentToolCallRepository
from src.application.ports.agent_verification_port import (
    AgentVerificationRepository,
)
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.infrastructure.agents.llm_chat_responder import LLMChatResponder
from src.infrastructure.agents.rule_based_personal_data_masker import (
    RuleBasedPersonalDataMasker,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.agent_chat_repositories import (
    DynamoAgentInsightRepository,
    DynamoAgentLinkRepository,
    DynamoAgentMessageRepository,
    DynamoAgentSessionSummaryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_repositories import (
    DynamoAgentBudgetLedgerRepository,
    DynamoAgentConfirmationRepository,
    DynamoAgentIterationRepository,
    DynamoAgentPackageRepository,
    DynamoAgentPromptRepository,
    DynamoAgentRunRepository,
    DynamoAgentToolCallRepository,
    DynamoAgentVerificationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_session_repository import (
    DynamoAgentSessionRepository,
)


@lru_cache
def get_agent_session_repository() -> AgentSessionRepository:
    return DynamoAgentSessionRepository()


@lru_cache
def get_agent_iteration_repository() -> AgentIterationRepository:
    return DynamoAgentIterationRepository()


@lru_cache
def get_agent_run_repository() -> AgentRunRepository:
    return DynamoAgentRunRepository()


@lru_cache
def get_agent_tool_call_repository() -> AgentToolCallRepository:
    return DynamoAgentToolCallRepository()


@lru_cache
def get_agent_budget_ledger_repository() -> AgentBudgetLedgerRepository:
    return DynamoAgentBudgetLedgerRepository()


@lru_cache
def get_agent_verification_repository() -> AgentVerificationRepository:
    return DynamoAgentVerificationRepository()


@lru_cache
def get_agent_package_repository() -> AgentPackageRepository:
    return DynamoAgentPackageRepository()


@lru_cache
def get_agent_confirmation_repository() -> AgentConfirmationRepository:
    return DynamoAgentConfirmationRepository()


@lru_cache
def get_agent_prompt_repository() -> AgentPromptRepository:
    return DynamoAgentPromptRepository()


@lru_cache
def get_agent_message_repository() -> AgentMessageRepository:
    return DynamoAgentMessageRepository()


@lru_cache
def get_agent_insight_repository() -> AgentInsightRepository:
    return DynamoAgentInsightRepository()


@lru_cache
def get_agent_link_repository() -> AgentLinkRepository:
    return DynamoAgentLinkRepository()


@lru_cache
def get_agent_session_summary_repository() -> AgentSessionSummaryRepository:
    return DynamoAgentSessionSummaryRepository()


@lru_cache
def get_personal_data_masker() -> PersonalDataMasker:
    return RuleBasedPersonalDataMasker()


@lru_cache
def get_agent_chat_responder() -> AgentChatResponder:
    model = genai_config.REPORT_LLM_MODEL or genai_config.EXECUTOR_LLM_MODEL
    return LLMChatResponder(
        llm_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=model,
    )
