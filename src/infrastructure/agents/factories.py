from __future__ import annotations

from functools import lru_cache

from src.application.ports.agent_audit_port import AgentAuditRepository
from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetLedgerRepository,
)
from src.application.ports.agent_chat_responder_port import AgentChatResponder
from src.application.ports.agent_confirmation_port import (
    AgentConfirmationRepository,
)
from src.application.ports.agent_entity_claim_port import AgentEntityClaimRepository
from src.application.ports.agent_event_port import AgentEventRepository
from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
)
from src.application.ports.agent_experiment_port import AgentExperimentRepository
from src.application.ports.agent_finding_port import AgentFindingRepository
from src.application.ports.agent_hypothesis_port import AgentHypothesisRepository
from src.application.ports.agent_insight_port import AgentInsightRepository
from src.application.ports.agent_iteration_port import AgentIterationRepository
from src.application.ports.agent_link_port import AgentLinkRepository
from src.application.ports.agent_message_port import AgentMessageRepository
from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.agent_package_port import AgentPackageRepository
from src.application.ports.agent_prompt_port import AgentPromptRepository
from src.application.ports.agent_release_port import AgentReleaseRepository
from src.application.ports.agent_run_port import AgentRunRepository
from src.application.ports.agent_session_port import AgentSessionRepository
from src.application.ports.agent_session_summary_port import (
    AgentSessionSummaryRepository,
)
from src.application.ports.agent_tool_call_port import AgentToolCallRepository
from src.application.ports.agent_verification_port import (
    AgentVerificationRepository,
)
from src.application.ports.optimization_run_port import OptimizationRunRepository
from src.application.ports.optimizer_insight_port import OptimizerInsightRepository
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.application.ports.project_graph_port import ProjectGraphRepository
from src.application.ports.project_graph_semantic_port import (
    ProjectGraphSemanticSearch,
)
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.application.use_cases.agent.optimizer_memory import OptimizerMemory
from src.infrastructure.agents.agent_experiment_component_resolver import (
    StoredAgentExperimentComponentResolver,
)
from src.infrastructure.agents.embedding_project_graph_search import (
    EmbeddingProjectGraphSemanticSearch,
)
from src.infrastructure.agents.json_project_graph_repository import (
    JsonProjectGraphRepository,
)
from src.infrastructure.agents.llm_chat_responder import LLMChatResponder
from src.infrastructure.agents.llm_structured_agent_generator import (
    LLMStructuredAgentGenerator,
)
from src.infrastructure.agents.modus_operandi_generator_subagent import (
    ModusOperandiGeneratorSubagent,
)
from src.infrastructure.agents.optimizer_specialist_subagent import (
    OptimizerSpecialistSubagent,
)
from src.infrastructure.agents.rule_based_personal_data_masker import (
    RuleBasedPersonalDataMasker,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.embedding.langchain import (
    get_embedding_unit_of_work_factory,
)
from src.infrastructure.llm.catalog.element_llm import get_element_llm_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_audit_repository import (
    DynamoAgentAuditRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_chat_repositories import (
    DynamoAgentInsightRepository,
    DynamoAgentLinkRepository,
    DynamoAgentMessageRepository,
    DynamoAgentSessionSummaryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_event_repositories import (
    DynamoAgentEventRepository,
    DynamoOptimizerInsightRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_objective_repository import (
    DynamoAgentObjectiveRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_release_repository import (
    DynamoAgentReleaseRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_repositories import (
    DynamoAgentBudgetLedgerRepository,
    DynamoAgentConfirmationRepository,
    DynamoAgentEntityClaimRepository,
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
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    DynamoConfigurationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import (
    DynamoModelRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.modus_operandi_library_repository import (
    DynamoModusOperandiLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.optimization_run_repositories import (
    DynamoOptimizationRunRepository,
    DynamoRunExperimentRepository,
    DynamoRunFindingRepository,
    DynamoRunHypothesisRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.vector_store_generation_repository import (
    DynamoVectorStoreGenerationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.vector_store_instance_repository import (
    DynamoVectorStoreInstanceRepository,
)
from src.infrastructure.persistence.object_storage.minio import get_model_object_storage


@lru_cache
def get_agent_session_repository() -> AgentSessionRepository:
    return DynamoAgentSessionRepository()


@lru_cache
def get_agent_experiment_component_resolver() -> AgentExperimentComponentResolver:
    return StoredAgentExperimentComponentResolver(
        models=DynamoModelRepository(),
        model_storage=get_model_object_storage(),
        configurations=DynamoConfigurationRepository(),
        library=DynamoModusOperandiLibraryRepository(),
        vector_stores=DynamoVectorStoreInstanceRepository(),
        vector_store_generations=DynamoVectorStoreGenerationRepository(),
    )


@lru_cache
def get_agent_audit_repository() -> AgentAuditRepository:
    return DynamoAgentAuditRepository()


@lru_cache
def get_agent_release_repository() -> AgentReleaseRepository:
    return DynamoAgentReleaseRepository()


@lru_cache
def get_agent_iteration_repository() -> AgentIterationRepository:
    return DynamoAgentIterationRepository()


@lru_cache
def get_agent_experiment_repository() -> AgentExperimentRepository:
    return DynamoRunExperimentRepository()


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
def get_agent_entity_claim_repository() -> AgentEntityClaimRepository:
    return DynamoAgentEntityClaimRepository()


@lru_cache
def get_agent_hypothesis_repository() -> AgentHypothesisRepository:
    return DynamoRunHypothesisRepository()


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
def get_agent_objective_repository() -> AgentObjectiveRepository:
    return DynamoAgentObjectiveRepository()


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
def get_project_graph_repository() -> ProjectGraphRepository:
    return JsonProjectGraphRepository()


@lru_cache
def get_project_graph_semantic_search() -> ProjectGraphSemanticSearch | None:
    """Embedding search over the project map; None (BM25 only) without a model."""
    if not genai_config.EMBEDDING_MODEL:
        return None
    return EmbeddingProjectGraphSemanticSearch(
        graph=get_project_graph_repository(),
        embeddings=get_embedding_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=genai_config.EMBEDDING_MODEL,
    )


@lru_cache
def get_agent_chat_responder() -> AgentChatResponder:
    model = genai_config.REPORT_LLM_MODEL or genai_config.EXECUTOR_LLM_MODEL
    return LLMChatResponder(
        llm_factory=get_element_llm_factory("assistant_chat"),
        monitoring=get_monitoring(),
        model=model,
    )


@lru_cache
def get_modus_operandi_generator_subagent() -> ModusOperandiGeneratorSubagent:
    model = genai_config.REPORT_LLM_MODEL or genai_config.EXECUTOR_LLM_MODEL
    generator = LLMStructuredAgentGenerator(
        llm_factory=get_element_llm_factory("agent_drafts"),
        monitoring=get_monitoring(),
        model=model,
    )
    return ModusOperandiGeneratorSubagent(generator)


@lru_cache
def get_optimizer_agent_specialists() -> dict[str, OptimizerSpecialistSubagent]:
    from src.infrastructure.agents.specialist_executor_factory import (
        get_optimizer_specialist_executors,
    )

    model = genai_config.REPORT_LLM_MODEL or genai_config.EXECUTOR_LLM_MODEL
    generator = LLMStructuredAgentGenerator(
        llm_factory=get_element_llm_factory("optimizer"),
        monitoring=get_monitoring(),
        model=model,
    )
    prompts = get_agent_prompt_repository()
    masker = get_personal_data_masker()
    executors = get_optimizer_specialist_executors()
    return {
        name: OptimizerSpecialistSubagent(
            name=name,
            prompt_name=f"agent.specialist.{prompt_suffix}",
            prompts=prompts,
            generator=generator,
            masker=masker,
            executor=executors[name],
            component_resolver=get_agent_experiment_component_resolver(),
        )
        for name, prompt_suffix in (
            ("configuration", "configuration"),
            ("library", "library"),
            ("vector_store", "vector_store"),
            ("xgboost", "xgboost"),
        )
    }


@lru_cache
def get_agent_event_repository() -> AgentEventRepository:
    return DynamoAgentEventRepository()


@lru_cache
def get_agent_finding_repository() -> AgentFindingRepository:
    return DynamoRunFindingRepository()


@lru_cache
def get_optimizer_insight_repository() -> OptimizerInsightRepository:
    return DynamoOptimizerInsightRepository()


def get_agent_timeline() -> AgentTimeline:
    return AgentTimeline(
        events=get_agent_event_repository(),
        clock=get_clock(),
        ids=get_id_generator(),
        audit=get_audit_repository(),
    )


def get_optimizer_memory() -> OptimizerMemory:
    return OptimizerMemory(
        findings=get_agent_finding_repository(),
        insights=get_optimizer_insight_repository(),
        clock=get_clock(),
        ids=get_id_generator(),
    )


@lru_cache
def get_optimization_run_repository() -> OptimizationRunRepository:
    return DynamoOptimizationRunRepository()
