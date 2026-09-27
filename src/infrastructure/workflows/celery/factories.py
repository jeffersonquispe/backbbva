from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from src.application.ports.configuration_port import AnalystPlaybook
from src.application.ports.workflow_status_port import WorkflowStatusReporter
from src.application.use_cases.alerts.adversarial_review_alert import (
    AdversarialReviewAlertUseCase,
)
from src.application.use_cases.alerts.analyst_review_alert import (
    AnalystReviewAlertUseCase,
)
from src.application.use_cases.alerts.classify_alert import ClassifyAlertUseCase
from src.application.use_cases.alerts.discard_alert import DiscardAlertUseCase
from src.application.use_cases.alerts.enrich_profiling_fields import (
    EnrichProfilingFieldsUseCase,
)
from src.application.use_cases.alerts.evaluate_deterministic_rules import (
    EvaluateDeterministicRulesUseCase,
)
from src.application.use_cases.alerts.generate_agent_text import (
    GenerateAgentTextUseCase,
)
from src.application.use_cases.alerts.post_process_alert import (
    PostProcessAlertUseCase,
)
from src.application.use_cases.alerts.pre_process_alert import (
    PreProcessAlertUseCase,
)
from src.application.use_cases.alerts.profile_alert import ProfileAlertUseCase
from src.application.use_cases.alerts.profile_alert_deterministic import (
    DeterministicProfileAlertUseCase,
)
from src.application.use_cases.alerts.resolve_analyst_playbook import (
    ResolveAnalystPlaybookUseCase,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)
from src.infrastructure.aric.mock.aric_alert_adapter import MockAricAlertAdapter
from src.infrastructure.core.config import genai_config
from src.infrastructure.embedding.langchain import get_embedding_unit_of_work_factory
from src.infrastructure.fraud_intelligence.mock.fraud_taxonomy_adapter import (
    MockFraudTaxonomyAdapter,
)
from src.infrastructure.fraud_intelligence.mock.modus_operandi_adapter import (
    MockModusOperandiAdapter,
)
from src.infrastructure.fraud_intelligence.mock.similar_fraud_case_adapter import (
    MockSimilarFraudCaseAdapter,
)
from src.infrastructure.fraud_intelligence.opensearch.fraud_taxonomy_adapter import (
    OpenSearchFraudTaxonomyAdapter,
)
from src.infrastructure.fraud_intelligence.opensearch.modus_operandi_adapter import (
    OpenSearchModusOperandiAdapter,
)
from src.infrastructure.fraud_intelligence.opensearch.similar_fraud_case_adapter import (
    OpenSearchSimilarFraudCaseAdapter,
)
from src.infrastructure.host_services.mock.customer_profile_adapter import (
    MockHostServiceCustomerProfileAdapter,
)
from src.infrastructure.host_services.mock.personal_data_changes_adapter import (
    MockHostServicePersonalDataChangesAdapter,
)
from src.infrastructure.host_services.mock.transaction_history_adapter import (
    MockHostServiceTransactionHistoryAdapter,
)
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    DynamoConfigurationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_playbook_repository import (
    DynamoFraudPlaybookRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.operations_capacity_repository import (
    DynamoOperationsCapacityRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.test_run_repository import (
    DynamoTestRunRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.vector_store_instance_repository import (
    DynamoVectorStoreInstanceRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.watchlist_repository import (
    DynamoWatchlistRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import (
    DynamoModelRepository,
)
from src.infrastructure.persistence.object_storage.minio import get_model_object_storage
from src.infrastructure.persistence.vector_store.opensearch.client import (
    get_opensearch_client,
)
from src.infrastructure.persistence.vector_store.opensearch.search import (
    OpenSearchFraudKnowledgeSearchAdapter,
)
from src.infrastructure.persistence.database.dynamodb.repositories.workflow_repository import (
    DynamoWorkflowExecutionRepository,
    DynamoWorkflowStepExecutionRepository,
)
from src.infrastructure.queues.celery.alert_action_dispatcher import (
    CeleryAlertActionDispatcher,
)
from src.infrastructure.queues.celery.analyst_decision_documenter_dispatcher import (
    CeleryAnalystDecisionDocumenter,
)
from src.infrastructure.queues.celery.analyst_escalation_dispatcher import (
    CeleryAnalystEscalationDispatcher,
)

# --- stateless adapters: one instance per worker process ---


@lru_cache
def get_alert_repository() -> DynamoAlertRepository:
    return DynamoAlertRepository()


@lru_cache
def get_configuration_repository() -> DynamoConfigurationRepository:
    return DynamoConfigurationRepository()


@lru_cache
def get_async_operation_repository() -> DynamoAsyncOperationRepository:
    return DynamoAsyncOperationRepository()


@lru_cache
def get_workflow_execution_repository() -> DynamoWorkflowExecutionRepository:
    return DynamoWorkflowExecutionRepository()


@lru_cache
def get_workflow_step_execution_repository() -> DynamoWorkflowStepExecutionRepository:
    return DynamoWorkflowStepExecutionRepository()


@lru_cache
def get_fraud_playbook_repository() -> DynamoFraudPlaybookRepository:
    return DynamoFraudPlaybookRepository()


@lru_cache
def get_operations_capacity_repository() -> DynamoOperationsCapacityRepository:
    return DynamoOperationsCapacityRepository()


@lru_cache
def get_test_run_repository() -> DynamoTestRunRepository:
    return DynamoTestRunRepository()


@lru_cache
def get_watchlist_repository() -> DynamoWatchlistRepository:
    return DynamoWatchlistRepository()


@lru_cache
def get_model_repository() -> DynamoModelRepository:
    return DynamoModelRepository()


@lru_cache
def get_model_storage():
    return get_model_object_storage()


@lru_cache
def get_aric_alert_port() -> MockAricAlertAdapter:
    return MockAricAlertAdapter()


@lru_cache
def get_host_customer_profile_port() -> MockHostServiceCustomerProfileAdapter:
    return MockHostServiceCustomerProfileAdapter()


@lru_cache
def get_host_transaction_history_port() -> MockHostServiceTransactionHistoryAdapter:
    return MockHostServiceTransactionHistoryAdapter()


@lru_cache
def get_host_personal_data_changes_port() -> MockHostServicePersonalDataChangesAdapter:
    return MockHostServicePersonalDataChangesAdapter()


@lru_cache
def get_vector_store_instance_repository() -> DynamoVectorStoreInstanceRepository:
    return DynamoVectorStoreInstanceRepository()


@lru_cache
def get_fraud_knowledge_search_port() -> OpenSearchFraudKnowledgeSearchAdapter:
    return OpenSearchFraudKnowledgeSearchAdapter(
        client=get_opensearch_client(),
        embedding_unit_of_work_factory=get_embedding_unit_of_work_factory(),
        monitoring=get_monitoring(),
        embedding_model=genai_config.EMBEDDING_MODEL,
    )


@lru_cache
def get_search_fraud_knowledge_use_case() -> SearchFraudKnowledgeUseCase:
    return SearchFraudKnowledgeUseCase(
        get_fraud_knowledge_search_port(), get_vector_store_instance_repository()
    )


@lru_cache
def get_resolve_analyst_playbook_use_case() -> ResolveAnalystPlaybookUseCase:
    return ResolveAnalystPlaybookUseCase(get_search_fraud_knowledge_use_case())


# similar_fraud_case_port/fraud_taxonomy_port/modus_operandi_port fall back to
# their Mocks when no vector store is selected for this segment/stage (mirrors
# _segment_tool_kwargs's own gating in alert_review_workflow.py - the tool is
# only enabled at all when vector_store_enabled AND an instance is picked, so
# the Mock branch here is never actually exercised by a real tool call, only
# by whatever passes no id at all). lru_cache still applies per
# vector_store_instance_id value - cheap, and these adapters are stateless.
@lru_cache
def get_similar_fraud_case_port(
    vector_store_instance_id: str | None = None,
) -> MockSimilarFraudCaseAdapter | OpenSearchSimilarFraudCaseAdapter:
    if vector_store_instance_id is None:
        return MockSimilarFraudCaseAdapter()
    return OpenSearchSimilarFraudCaseAdapter(
        get_search_fraud_knowledge_use_case(), vector_store_instance_id
    )


@lru_cache
def get_fraud_taxonomy_port(
    vector_store_instance_id: str | None = None,
) -> MockFraudTaxonomyAdapter | OpenSearchFraudTaxonomyAdapter:
    if vector_store_instance_id is None:
        return MockFraudTaxonomyAdapter()
    return OpenSearchFraudTaxonomyAdapter(
        get_search_fraud_knowledge_use_case(), vector_store_instance_id
    )


@lru_cache
def get_modus_operandi_port(
    vector_store_instance_id: str | None = None,
) -> MockModusOperandiAdapter | OpenSearchModusOperandiAdapter:
    if vector_store_instance_id is None:
        return MockModusOperandiAdapter()
    return OpenSearchModusOperandiAdapter(
        get_search_fraud_knowledge_use_case(), vector_store_instance_id
    )


@lru_cache
def get_analyst_escalation_dispatcher() -> CeleryAnalystEscalationDispatcher:
    return CeleryAnalystEscalationDispatcher()


@lru_cache
def get_analyst_decision_documenter() -> CeleryAnalystDecisionDocumenter:
    return CeleryAnalystDecisionDocumenter()


@lru_cache
def get_alert_action_dispatcher() -> CeleryAlertActionDispatcher:
    return CeleryAlertActionDispatcher()


# --- use cases: fresh instance per call, wired from the singletons above ---


def get_pre_process_alert_use_case(
    *,
    status_reporter: WorkflowStatusReporter | None,
    workflow_execution_id: UUID | None,
    step_id: UUID | None,
) -> PreProcessAlertUseCase:
    return PreProcessAlertUseCase(
        aric_alert_port=get_aric_alert_port(),
        host_customer_profile_port=get_host_customer_profile_port(),
        host_transaction_history_port=get_host_transaction_history_port(),
        host_personal_data_changes_port=get_host_personal_data_changes_port(),
        status_reporter=status_reporter,
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )


def get_profile_alert_use_case(
    *,
    status_reporter: WorkflowStatusReporter | None,
    workflow_execution_id: UUID | None,
    step_id: UUID | None,
    system_prompt: str | None = None,
    model: str | None = None,
    extra_instructions: dict[str, str] | None = None,
) -> ProfileAlertUseCase | DeterministicProfileAlertUseCase:
    backend = genai_config.PROFILING_BACKEND.strip().lower()
    if backend == "deterministic":
        return DeterministicProfileAlertUseCase(
            status_reporter=status_reporter,
            workflow_execution_id=workflow_execution_id,
            step_id=step_id,
        )
    if backend == "llm":
        return ProfileAlertUseCase(
            llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
            monitoring=get_monitoring(),
            model=model or genai_config.PROFILING_LLM_MODEL,
            system_prompt=system_prompt,
            extra_instructions=extra_instructions,
            status_reporter=status_reporter,
            workflow_execution_id=workflow_execution_id,
            step_id=step_id,
        )
    raise ValueError(f"Unsupported profiling backend: {backend}")


def get_enrich_profiling_fields_use_case() -> EnrichProfilingFieldsUseCase:
    return EnrichProfilingFieldsUseCase()


def get_evaluate_deterministic_rules_use_case() -> EvaluateDeterministicRulesUseCase:
    return EvaluateDeterministicRulesUseCase()


def get_discard_alert_use_case() -> DiscardAlertUseCase:
    return DiscardAlertUseCase(monitoring=get_monitoring())


def get_classify_alert_use_case(
    *,
    status_reporter: WorkflowStatusReporter | None,
    workflow_execution_id: UUID | None,
    step_id: UUID | None,
    system_prompt: str | None = None,
    model: str | None = None,
    extra_instructions: str | None = None,
    enabled_tools: set[str] | None = None,
    watchlist_ids: list[str] | None = None,
    watchlist_compare_field: str | None = None,
    output_labels: list[str] | None = None,
    max_iterations: int | None = None,
    step_name: str = "classification",
    vector_store_instance_id: str | None = None,
) -> ClassifyAlertUseCase:
    default_model = (
        genai_config.DETECTOR_LLM_MODEL
        if step_name == "detector"
        else genai_config.CLASSIFICATION_LLM_MODEL
    )
    return ClassifyAlertUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=model or default_model,
        similar_fraud_case_port=get_similar_fraud_case_port(vector_store_instance_id),
        fraud_taxonomy_port=get_fraud_taxonomy_port(vector_store_instance_id),
        modus_operandi_port=get_modus_operandi_port(vector_store_instance_id),
        system_prompt=system_prompt,
        extra_instructions=extra_instructions,
        enabled_tools=enabled_tools,
        watchlist_repository=get_watchlist_repository(),
        watchlist_ids=watchlist_ids,
        watchlist_compare_field=watchlist_compare_field,
        output_labels=output_labels,
        max_iterations=max_iterations,
        step_name=step_name,
        status_reporter=status_reporter,
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )


def get_adversarial_review_alert_use_case(
    *,
    status_reporter: WorkflowStatusReporter | None,
    workflow_execution_id: UUID | None,
    step_id: UUID | None,
    system_prompt: str | None = None,
    model: str | None = None,
    extra_instructions: str | None = None,
    enabled_tools: set[str] | None = None,
    watchlist_ids: list[str] | None = None,
    watchlist_compare_field: str | None = None,
    max_iterations: int | None = None,
    step_name: str = "adversarial",
    vector_store_instance_id: str | None = None,
) -> AdversarialReviewAlertUseCase:
    default_model = (
        genai_config.DETECTOR_ADVERSARIAL_LLM_MODEL
        if step_name == "detector_adversarial"
        else genai_config.ADVERSARIAL_LLM_MODEL
    )
    return AdversarialReviewAlertUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=model or default_model,
        similar_fraud_case_port=get_similar_fraud_case_port(vector_store_instance_id),
        fraud_taxonomy_port=get_fraud_taxonomy_port(vector_store_instance_id),
        modus_operandi_port=get_modus_operandi_port(vector_store_instance_id),
        system_prompt=system_prompt,
        extra_instructions=extra_instructions,
        enabled_tools=enabled_tools,
        watchlist_repository=get_watchlist_repository(),
        watchlist_ids=watchlist_ids,
        watchlist_compare_field=watchlist_compare_field,
        max_iterations=max_iterations,
        step_name=step_name,
        status_reporter=status_reporter,
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )


def get_analyst_review_alert_use_case(
    *,
    status_reporter: WorkflowStatusReporter | None,
    workflow_execution_id: UUID | None,
    step_id: UUID | None,
    system_prompt: str | None = None,
    model: str | None = None,
    playbooks: list[AnalystPlaybook] | None = None,
    vector_store_instance_id: str | None = None,
    handling_prompt: str = "",
) -> AnalystReviewAlertUseCase:
    return AnalystReviewAlertUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=model or genai_config.ANALYST_LLM_MODEL,
        fraud_playbook_port=get_fraud_playbook_repository(),
        operations_capacity_port=get_operations_capacity_repository(),
        resolve_analyst_playbook=get_resolve_analyst_playbook_use_case(),
        system_prompt=system_prompt,
        status_reporter=status_reporter,
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
        playbooks=playbooks,
        vector_store_instance_id=vector_store_instance_id,
        handling_prompt=handling_prompt,
    )


def get_post_process_alert_use_case() -> PostProcessAlertUseCase:
    return PostProcessAlertUseCase()


def get_generate_agent_text_use_case(
    *,
    system_prompt: str,
    operation_name: str,
    model: str | None = None,
) -> GenerateAgentTextUseCase:
    return GenerateAgentTextUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=model or genai_config.EXECUTOR_LLM_MODEL,
        system_prompt=system_prompt,
        operation_name=operation_name,
    )
