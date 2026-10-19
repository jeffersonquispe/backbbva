from __future__ import annotations

from functools import lru_cache

from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetLedgerRepository,
)
from src.application.ports.agent_confirmation_port import (
    AgentConfirmationRepository,
)
from src.application.ports.agent_iteration_port import AgentIterationRepository
from src.application.ports.agent_package_port import AgentPackageRepository
from src.application.ports.agent_prompt_port import AgentPromptRepository
from src.application.ports.agent_run_port import AgentRunRepository
from src.application.ports.agent_session_port import AgentSessionRepository
from src.application.ports.agent_tool_call_port import AgentToolCallRepository
from src.application.ports.agent_verification_port import (
    AgentVerificationRepository,
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
