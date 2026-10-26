from __future__ import annotations

from functools import lru_cache
from typing import cast
from uuid import UUID

from src.application.ports.agent_subagent_port import AgentSubagent
from src.application.ports.alert_payload_source_port import AlertPayloadSource
from src.application.ports.alert_port import AlertRepository
from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.alert_schema_presence_report_port import (
    AlertSchemaPresenceReportRepository,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.async_operation_port import AsyncOperationRepository
from src.application.ports.configuration_port import ConfigurationRepository
from src.application.ports.metrics_rollup_port import MetricsRollupRepository
from src.application.ports.model_port import ModelRepository
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.ports.operations_capacity_port import OperationsCapacityPort
from src.application.ports.resource_reservation_port import (
    ResourceReservationRepository,
)
from src.application.ports.test_run_port import TestRunRepository
from src.application.ports.vector_store_instance_port import (
    VectorStoreInstanceRepository,
)
from src.application.ports.watchlist_port import WatchlistRepository
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.ports.workflow_status_port import WorkflowStatusReporter
from src.application.ports.workflow_step_execution_port import (
    WorkflowStepExecutionRepository,
)
from src.application.use_cases.agent.orchestrate_agent_iteration import (
    OrchestrateAgentIterationUseCase,
)
from src.application.use_cases.agent.recover_stale_agent_runs import (
    RecoverStaleAgentRunsUseCase,
)
from src.application.use_cases.alert_schema.analyze_presence import (
    AnalyzeAlertSchemaPresenceUseCase,
)
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
from src.application.use_cases.alerts.post_process_alert import PostProcessAlertUseCase
from src.application.use_cases.alerts.pre_process_alert import PreProcessAlertUseCase
from src.application.use_cases.alerts.profile_alert import ProfileAlertUseCase
from src.application.use_cases.alerts.profile_alert_deterministic import (
    DeterministicProfileAlertUseCase,
)
from src.application.use_cases.alerts.resolve_analyst_playbook import (
    ResolveAnalystPlaybookUseCase,
)
from src.application.use_cases.alerts.route_alert_resolution import (
    RouteAlertResolutionUseCase,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)
from src.application.use_cases.metrics.backfill_alert_metrics import (
    BackfillAlertMetrics,
)
from src.application.use_cases.metrics.evaluate_alert_reasoning import (
    EvaluateAlertReasoning,
)
from src.application.use_cases.metrics.reconcile_alert_rollups import (
    ReconcileAlertRollups,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.application.use_cases.metrics.record_workflow_step_metrics import (
    RecordWorkflowStepMetrics,
)
from src.application.use_cases.operations.live_operations_capacity import (
    LiveOperationsCapacity,
)
from src.application.use_cases.research.research_tool import BoundedResearchTool
from src.infrastructure.agents.agent_experiment_component_resolver import (
    StoredAgentExperimentComponentResolver,
)
from src.infrastructure.agents.factories import (
    get_agent_budget_ledger_repository,
    get_agent_experiment_repository,
    get_agent_hypothesis_repository,
    get_agent_insight_repository,
    get_agent_iteration_repository,
    get_agent_link_repository,
    get_agent_objective_repository,
    get_agent_package_repository,
    get_agent_run_repository,
    get_agent_session_repository,
    get_agent_session_summary_repository,
    get_agent_timeline,
    get_agent_verification_repository,
    get_optimizer_agent_specialists,
    get_optimizer_memory,
)
from src.infrastructure.agents.stub_subagent import StubAgentSubagent
from src.infrastructure.alerts.storage.stored_alert_payload_adapter import (
    StoredAlertPayloadAdapter,
)
from src.infrastructure.aric.mock.aric_alert_adapter import MockAricAlertAdapter
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
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
from src.infrastructure.persistence.database.dynamodb.repositories.alert_lifecycle_reader import (
    DynamoAlertLifecycleReader,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_reasoning_evaluation_repository import (
    DynamoAlertReasoningEvaluationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_schema_presence_repository import (
    DynamoAlertSchemaPresenceReportRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_schema_repository import (
    DynamoAlertSchemaRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.assistant_optimizer_settings_repository import (
    DynamoAssistantOptimizerSettingsRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    DynamoConfigurationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.metrics_rollup_repository import (
    DynamoMetricsRollupRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import (
    DynamoModelRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.modus_operandi_library_repository import (
    DynamoModusOperandiLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.operational_settings_repository import (
    DynamoOperationalSettingsRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.operations_capacity_repository import (
    DynamoOperationsCapacityRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.resource_reservation_repository import (
    DynamoResourceReservationRepository,
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
from src.infrastructure.persistence.database.dynamodb.repositories.workflow_repository import (
    DynamoWorkflowExecutionRepository,
    DynamoWorkflowStepExecutionRepository,
)
from src.infrastructure.persistence.object_storage.minio import (
    get_model_object_storage,
    get_object_storage,
)
from src.infrastructure.persistence.vector_store.opensearch.client import (
    get_opensearch_client,
)
from src.infrastructure.persistence.vector_store.opensearch.search import (
    OpenSearchFraudKnowledgeSearchAdapter,
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
from src.infrastructure.queues.celery.reasoning_evaluation_dispatcher import (
    CeleryReasoningEvaluationDispatcher,
)

# --- stateless adapters: one instance per worker process ---


@lru_cache
def get_alert_repository() -> AlertRepository:
    return DynamoAlertRepository()


@lru_cache
def get_alert_schema_repository() -> AlertSchemaRepository:
    return DynamoAlertSchemaRepository()


@lru_cache
def get_alert_payload_source() -> AlertPayloadSource:
    return StoredAlertPayloadAdapter(
        alerts=get_alert_repository(), object_storage=get_alert_object_storage()
    )


@lru_cache
def get_alert_schema_presence_report_repository() -> (
    AlertSchemaPresenceReportRepository
):
    return DynamoAlertSchemaPresenceReportRepository()


def get_analyze_alert_schema_presence_use_case() -> AnalyzeAlertSchemaPresenceUseCase:
    return AnalyzeAlertSchemaPresenceUseCase(
        get_alert_repository(),
        get_alert_schema_repository(),
        get_alert_schema_presence_report_repository(),
        get_object_storage(),
        clock=get_clock(),
    )


@lru_cache
def get_metrics_rollup_repository() -> MetricsRollupRepository:
    return DynamoMetricsRollupRepository(timezone_name=genai_config.OPERATIONS_TIMEZONE)


@lru_cache
def get_metrics_rollup_maintenance_repository() -> DynamoMetricsRollupRepository:
    """Concrete maintenance adapter for bounded expired-row cleanup."""
    return DynamoMetricsRollupRepository(timezone_name=genai_config.OPERATIONS_TIMEZONE)


@lru_cache
def get_configuration_repository() -> ConfigurationRepository:
    return DynamoConfigurationRepository()


@lru_cache
def get_async_operation_repository() -> AsyncOperationRepository:
    return DynamoAsyncOperationRepository()


@lru_cache
def get_workflow_execution_repository() -> WorkflowExecutionRepository:
    return DynamoWorkflowExecutionRepository()


@lru_cache
def get_workflow_step_execution_repository() -> WorkflowStepExecutionRepository:
    return DynamoWorkflowStepExecutionRepository()


@lru_cache
def get_operations_capacity_repository() -> OperationsCapacityPort:
    return DynamoOperationsCapacityRepository()


@lru_cache
def get_operational_settings_repository() -> OperationalSettingsRepository:
    return DynamoOperationalSettingsRepository()


@lru_cache
def get_resource_reservation_repository() -> ResourceReservationRepository:
    return DynamoResourceReservationRepository()


@lru_cache
def get_modus_operandi_library_repository() -> ModusOperandiLibraryRepository:
    return DynamoModusOperandiLibraryRepository()


@lru_cache
def get_live_operations_capacity() -> LiveOperationsCapacity:
    return LiveOperationsCapacity(
        settings_repository=get_operational_settings_repository(),
        reservation_repository=get_resource_reservation_repository(),
        static_capacity=get_operations_capacity_repository(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
        clock=get_clock(),
    )


@lru_cache
def get_test_run_repository() -> TestRunRepository:
    return DynamoTestRunRepository()


@lru_cache
def get_watchlist_repository() -> WatchlistRepository:
    return DynamoWatchlistRepository()


@lru_cache
def get_model_repository() -> ModelRepository:
    return DynamoModelRepository()


@lru_cache
def get_model_storage():
    return get_model_object_storage()


@lru_cache
def get_alert_object_storage():
    return get_object_storage()


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
def get_vector_store_instance_repository() -> VectorStoreInstanceRepository:
    return DynamoVectorStoreInstanceRepository()


@lru_cache
def get_agent_experiment_component_resolver():
    return StoredAgentExperimentComponentResolver(
        models=get_model_repository(),
        model_storage=get_model_storage(),
        configurations=get_configuration_repository(),
        library=get_modus_operandi_library_repository(),
        vector_stores=get_vector_store_instance_repository(),
    )


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
    return ResolveAnalystPlaybookUseCase(
        get_search_fraud_knowledge_use_case(), get_modus_operandi_library_repository()
    )


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
    library_revision_pin: dict[str, str] | None = None,
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


@lru_cache
def get_reasoning_evaluation_dispatcher() -> CeleryReasoningEvaluationDispatcher:
    return CeleryReasoningEvaluationDispatcher()


@lru_cache
def get_alert_reasoning_evaluation_repository() -> (
    DynamoAlertReasoningEvaluationRepository
):
    return DynamoAlertReasoningEvaluationRepository()


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
        schema_repository=get_alert_schema_repository(),
        alert_payload_source=get_alert_payload_source(),
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
    vector_store_research: BoundedResearchTool | None = None,
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
        vector_store_research=vector_store_research,
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
    vector_store_research: BoundedResearchTool | None = None,
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
        vector_store_research=vector_store_research,
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
    vector_store_instance_id: str | None = None,
    library_revision_pin: dict[str, str] | None = None,
    handling_prompt: str = "",
) -> AnalystReviewAlertUseCase:
    return AnalystReviewAlertUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=model or genai_config.ANALYST_LLM_MODEL,
        operations_capacity_port=get_live_operations_capacity(),
        resolve_analyst_playbook=get_resolve_analyst_playbook_use_case(),
        system_prompt=system_prompt,
        status_reporter=status_reporter,
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
        vector_store_instance_id=vector_store_instance_id,
        library_revision_pin=library_revision_pin,
        handling_prompt=handling_prompt,
    )


def get_route_alert_resolution_use_case() -> RouteAlertResolutionUseCase:
    return RouteAlertResolutionUseCase(
        operations_capacity=get_live_operations_capacity(),
        settings_repository=get_operational_settings_repository(),
        reservation_repository=get_resource_reservation_repository(),
        clock=get_clock(),
    )


def get_record_alert_metrics_event_use_case() -> RecordAlertMetricsEvent:
    return RecordAlertMetricsEvent(
        alert_repository=get_alert_repository(),
        rollup_repository=get_metrics_rollup_repository(),
        settings_repository=get_operational_settings_repository(),
        schema_repository=DynamoAlertSchemaRepository(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
        monitoring=get_monitoring(),
        clock=get_clock(),
    )


@lru_cache
def get_fraud_label_review_repository():
    from src.infrastructure.persistence.database.dynamodb.repositories.fraud_label_review_repository import (
        DynamoFraudLabelReviewRepository,
    )

    return DynamoFraudLabelReviewRepository()


def get_import_fraud_label_reviews_use_case():
    """Bulk CSV fraud_label review (C5) - used by tasks.py's
    import_fraud_label_reviews_task."""
    from src.application.use_cases.fraud_review.import_fraud_label_reviews import (
        ImportFraudLabelReviews,
    )
    from src.application.use_cases.fraud_review.review_fraud_label import (
        ReviewFraudLabel,
    )

    return ImportFraudLabelReviews(
        review_fraud_label=ReviewFraudLabel(
            alert_repository=get_alert_repository(),
            review_repository=get_fraud_label_review_repository(),
            record_metrics_event=get_record_alert_metrics_event_use_case(),
            monitoring=get_monitoring(),
            clock=get_clock(),
            id_generator=get_id_generator(),
        )
    )


def get_post_process_alert_use_case() -> PostProcessAlertUseCase:
    return PostProcessAlertUseCase(clock=get_clock())


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


def llm_step_models(model_overrides: dict[str, str] | None = None) -> dict[str, str]:
    """LLM step name -> the model it runs with: a test run's per-step
    override, else the same config default the step's factory above uses.
    Feeds the `model` dimension of the llm_call rollups. profiling is an
    LLM step only with PROFILING_BACKEND=llm."""
    defaults = {
        "detector": genai_config.DETECTOR_LLM_MODEL,
        "detector_adversarial": genai_config.DETECTOR_ADVERSARIAL_LLM_MODEL,
        "classification": genai_config.CLASSIFICATION_LLM_MODEL,
        "adversarial": genai_config.ADVERSARIAL_LLM_MODEL,
        "analyst": genai_config.ANALYST_LLM_MODEL,
        "executor": genai_config.EXECUTOR_LLM_MODEL,
    }
    if genai_config.PROFILING_BACKEND.strip().lower() == "llm":
        defaults["profiling"] = genai_config.PROFILING_LLM_MODEL
    overrides = model_overrides or {}
    return {step: overrides.get(step) or model for step, model in defaults.items()}


def get_record_workflow_step_metrics_use_case() -> RecordWorkflowStepMetrics:
    return RecordWorkflowStepMetrics(
        alert_repository=get_alert_repository(),
        step_repository=get_workflow_step_execution_repository(),
        rollup_repository=get_metrics_rollup_repository(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
        clock=get_clock(),
    )


def get_evaluate_alert_reasoning_use_case() -> EvaluateAlertReasoning:
    return EvaluateAlertReasoning(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=genai_config.JUDGE_LLM_MODEL or genai_config.REPORT_LLM_MODEL,
        alert_repository=get_alert_repository(),
        workflow_repository=get_workflow_execution_repository(),
        step_repository=get_workflow_step_execution_repository(),
        evaluation_repository=get_alert_reasoning_evaluation_repository(),
        rollup_repository=get_metrics_rollup_repository(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
        clock=get_clock(),
    )


def get_backfill_alert_metrics_use_case() -> BackfillAlertMetrics:
    # The lifecycle reader caches one Scan of resource_reservations, so it
    # is built fresh per use case (per run), never an lru_cache singleton.
    return BackfillAlertMetrics(
        alert_repository=get_alert_repository(),
        lifecycle_reader=DynamoAlertLifecycleReader(
            workflow_repository=get_workflow_execution_repository(),
            step_repository=get_workflow_step_execution_repository(),
        ),
        recorder=get_record_alert_metrics_event_use_case(),
    )


def get_reconcile_alert_rollups_use_case() -> ReconcileAlertRollups:
    return ReconcileAlertRollups(
        alert_repository=get_alert_repository(),
        rollup_repository=get_metrics_rollup_repository(),
        monitoring=get_monitoring(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
        backfill=get_backfill_alert_metrics_use_case(),
        clock=get_clock(),
    )


def get_record_operational_state_use_case():
    """T3/T5 operational gauges - used by tasks.py's
    record_operational_state (Beat, every 60 s)."""
    from src.application.use_cases.metrics.record_operational_state import (
        RecordOperationalState,
    )

    return RecordOperationalState(
        settings_repository=get_operational_settings_repository(),
        alert_repository=get_alert_repository(),
        operations_capacity=get_live_operations_capacity(),
        monitoring=get_monitoring(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
        clock=get_clock(),
    )


@lru_cache
def get_assistant_optimizer_settings_repository() -> AssistantOptimizerSettingsPort:
    """Shared live settings adapter for agent API and worker composition."""
    return DynamoAssistantOptimizerSettingsRepository()


def get_orchestrate_agent_iteration_use_case(
    settings: AssistantOptimizerSettingsPort | None = None,
    subagent: AgentSubagent | None = None,
) -> OrchestrateAgentIterationUseCase:
    """Compose the agent tick with the live Dynamo settings repository."""
    from src.application.use_cases.agent.evaluate_agent_experiment import (
        EvaluateAgentExperiment,
    )
    from src.application.use_cases.agent.paired_agent_experiment_runner import (
        PairedAgentExperimentRunner,
    )
    from src.infrastructure.agents.factories import (
        get_agent_audit_repository,
        get_agent_experiment_component_resolver,
        get_agent_experiment_repository,
        get_project_graph_repository,
    )
    from src.infrastructure.workflows.celery.task_factories import (
        get_agent_pipeline_replay_scorer,
        get_dataset_repository,
        get_dataset_snapshot_repository,
    )

    component_resolver = get_agent_experiment_component_resolver()
    pipeline_runner = PairedAgentExperimentRunner(
        components=component_resolver,
        scorer=get_agent_pipeline_replay_scorer(),
        objectives=get_agent_objective_repository(),
    )
    experiment_evaluator = EvaluateAgentExperiment(
        experiments=get_agent_experiment_repository(),
        objectives=get_agent_objective_repository(),
        evaluator=pipeline_runner,
        snapshots=get_dataset_snapshot_repository(),
        datasets=get_dataset_repository(),
        clock=get_clock(),
    )
    return OrchestrateAgentIterationUseCase(
        sessions=get_agent_session_repository(),
        iterations=get_agent_iteration_repository(),
        runs=get_agent_run_repository(),
        budget=get_agent_budget_ledger_repository(),
        packages=get_agent_package_repository(),
        verifications=get_agent_verification_repository(),
        hypotheses=get_agent_hypothesis_repository(),
        insights=get_agent_insight_repository(),
        links=get_agent_link_repository(),
        summaries=get_agent_session_summary_repository(),
        settings=settings or get_assistant_optimizer_settings_repository(),
        subagent=subagent or StubAgentSubagent(genai_config.AGENT_STUB_DELAY_SECONDS),
        specialists=cast(dict[str, AgentSubagent], get_optimizer_agent_specialists()),
        objectives=get_agent_objective_repository(),
        audit=get_agent_audit_repository(),
        components=component_resolver,
        experiment_evaluator=experiment_evaluator,
        project_graph=get_project_graph_repository(),
        monitoring=get_monitoring(),
        clock=get_clock(),
        id_generator=get_id_generator(),
        timeline=get_agent_timeline(),
        memory=get_optimizer_memory(),
    )


def get_recover_stale_agent_runs_use_case() -> RecoverStaleAgentRunsUseCase:
    return RecoverStaleAgentRunsUseCase(
        sessions=get_agent_session_repository(),
        iterations=get_agent_iteration_repository(),
        runs=get_agent_run_repository(),
        experiments=get_agent_experiment_repository(),
        clock=get_clock(),
        timeline=get_agent_timeline(),
        monitoring=get_monitoring(),
    )


def get_agent_entity_claim_use_case():
    from src.application.use_cases.agent.manage_agent_entity_claims import (
        AgentEntityClaimUseCase,
    )
    from src.infrastructure.agents.factories import (
        get_agent_entity_claim_repository,
        get_agent_session_repository,
    )

    return AgentEntityClaimUseCase(
        sessions=get_agent_session_repository(),
        claims=get_agent_entity_claim_repository(),
        clock=get_clock(),
    )
