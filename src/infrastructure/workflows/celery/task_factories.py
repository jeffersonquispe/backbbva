from __future__ import annotations

from functools import lru_cache
from src.application.use_cases.research.research_tool import BoundedResearchTool
from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.application.use_cases.alerts.document_analyst_decision import (
    DocumentAnalystDecisionUseCase,
)
from src.application.use_cases.alerts.escalate_alert_to_analyst import (
    EscalateAlertToAnalystUseCase,
)
from src.application.use_cases.alerts.execute_alert_action import (
    ExecuteAlertActionUseCase,
)
from src.application.use_cases.async_operations.reconcile_async_operations import (
    ReconcileAsyncOperationsUseCase,
)
from src.application.use_cases.datasets.analyze_dataset import AnalyzeDatasetUseCase
from src.application.use_cases.datasets.analyze_fraud_marking import (
    AnalyzeFraudMarkingUseCase,
)
from src.application.use_cases.datasets.delete_dataset import DeleteDatasetUseCase
from src.application.use_cases.test_runs.cleanup_test_runs import CleanupTestRunsUseCase
from src.application.use_cases.test_runs.delete_test_runs import DeleteTestRunsUseCase
from src.application.use_cases.test_runs.list_test_runs import ListTestRunsUseCase
from src.infrastructure.alert_actions.mock.alert_channel_action_adapter import (
    MockAlertChannelActionAdapter,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_sample_repository import (
    DynamoDatasetSampleRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_summary_repository import (
    DynamoDatasetSummaryRepository,
)
from src.infrastructure.persistence.dataset.minio.csv_dataset_repository import (
    MinioCsvDatasetRepository,
)
from src.infrastructure.persistence.object_storage.minio import (
    get_dataset_object_storage,
)
from src.infrastructure.queues.celery.inspector import CeleryAsyncExecutionInspector
from src.application.dtos.research_dtos import ResearchSource
from src.application.ports.configuration_port import (
    HistoryPandasResearchConfig,
    VectorStoreResearchConfig,
)
from src.application.ports.research_port import HistoryResearchPlanner
from src.application.use_cases.alerts.raw_payload import RawAlertPayloadLoader
from src.application.use_cases.alerts.resolve_alert_segment import (
    ResolveAlertSegmentUseCase,
)
from src.application.use_cases.research.delegated_research import (
    ResearchDelegationCoordinator,
    TimeBoundedResearchAgent,
    VectorStoreResearchAgent,
)
from src.infrastructure.workflows.celery.research_adapters import (
    WorkflowVectorStoreRetriever,
)
from src.infrastructure.workflows.celery.factories import (
    get_alert_object_storage,
    get_alert_repository,
    get_aric_alert_port,
    get_async_operation_repository,
    get_search_fraud_knowledge_use_case,
    get_test_run_repository,
    get_workflow_execution_repository,
    get_workflow_step_execution_repository,
)


# --- task-level wiring: everything entrypoint/worker/celery/tasks.py runs ---


@lru_cache
def get_dataset_sample_repository() -> DynamoDatasetSampleRepository:
    return DynamoDatasetSampleRepository()


@lru_cache
def get_dataset_summary_repository() -> DynamoDatasetSummaryRepository:
    return DynamoDatasetSummaryRepository()


@lru_cache
def get_dataset_repository() -> MinioCsvDatasetRepository:
    return MinioCsvDatasetRepository(get_dataset_object_storage())


@lru_cache
def get_alert_channel_action_port() -> MockAlertChannelActionAdapter:
    return MockAlertChannelActionAdapter()


@lru_cache
def get_async_execution_inspector() -> CeleryAsyncExecutionInspector:
    return CeleryAsyncExecutionInspector()


def get_reconcile_async_operations_use_case() -> ReconcileAsyncOperationsUseCase:
    return ReconcileAsyncOperationsUseCase(
        repository=get_async_operation_repository(),
        inspector=get_async_execution_inspector(),
    )


def get_cleanup_test_runs_use_case() -> CleanupTestRunsUseCase:
    workflows = get_workflow_execution_repository()
    return CleanupTestRunsUseCase(
        list_test_runs=ListTestRunsUseCase(get_test_run_repository(), workflows),
        delete_test_runs=DeleteTestRunsUseCase(
            test_run_repository=get_test_run_repository(),
            workflow_repository=workflows,
            step_repository=get_workflow_step_execution_repository(),
            alert_repository=get_alert_repository(),
            async_operation_repository=get_async_operation_repository(),
        ),
    )


def get_escalate_alert_to_analyst_use_case() -> EscalateAlertToAnalystUseCase:
    return EscalateAlertToAnalystUseCase(
        aric_alert_port=get_aric_alert_port(),
        monitoring=get_monitoring(),
    )


def get_document_analyst_decision_use_case() -> DocumentAnalystDecisionUseCase:
    return DocumentAnalystDecisionUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=genai_config.REPORT_LLM_MODEL,
        object_storage_port=get_alert_object_storage(),
    )


def get_execute_alert_action_use_case() -> ExecuteAlertActionUseCase:
    return ExecuteAlertActionUseCase(
        alert_action_port=get_alert_channel_action_port(),
        monitoring=get_monitoring(),
    )


def get_analyze_dataset_use_case() -> AnalyzeDatasetUseCase:
    return AnalyzeDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        sample_repository=get_dataset_sample_repository(),
        summary_repository=get_dataset_summary_repository(),
        max_input_bytes=genai_config.DATASET_ANALYSIS_MAX_BYTES,
    )


def get_delete_dataset_use_case() -> DeleteDatasetUseCase:
    return DeleteDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        sample_repository=get_dataset_sample_repository(),
        summary_repository=get_dataset_summary_repository(),
    )


def get_analyze_fraud_marking_use_case() -> AnalyzeFraudMarkingUseCase:
    return AnalyzeFraudMarkingUseCase(
        get_dataset_repository(),
        get_dataset_summary_repository(),
    )


# --- alert review workflow collaborators (AlertReviewWorkflowRunner) ---


def get_raw_alert_payload_loader() -> RawAlertPayloadLoader:
    return RawAlertPayloadLoader(get_alert_object_storage())


def get_resolve_alert_segment_use_case() -> ResolveAlertSegmentUseCase:
    return ResolveAlertSegmentUseCase()


def get_vector_store_research_tool(
    config: VectorStoreResearchConfig,
) -> BoundedResearchTool:
    """Bounded ``search_vector_store`` tool for one configured instance."""
    return BoundedResearchTool(
        TimeBoundedResearchAgent(
            VectorStoreResearchAgent(
                WorkflowVectorStoreRetriever(
                    get_search_fraud_knowledge_use_case(),
                    config.vector_store_instance_id,
                ),
                config,
            ),
            ResearchSource.VECTOR_STORE,
            config.timeout_seconds,
            monitoring=get_monitoring(),
        ),
        ResearchSource.VECTOR_STORE,
        max_interactions=config.max_delegations,
    )


def get_history_research_agent(
    planner: HistoryResearchPlanner,
    config: HistoryPandasResearchConfig,
    history_provider,
) -> TimeBoundedResearchAgent:
    # Lazy: the pandas-backed agent must not load with this module (the API
    # process imports it transitively and doesn't carry pandas).
    from src.infrastructure.workflows.celery.history_pandas_research import (
        HistoryPandasResearchAgent,
    )

    return TimeBoundedResearchAgent(
        HistoryPandasResearchAgent(planner, config, history_provider=history_provider),
        ResearchSource.HISTORY_PANDAS,
        config.timeout_seconds,
        monitoring=get_monitoring(),
    )


def get_research_delegation_coordinator(agents: dict) -> ResearchDelegationCoordinator:
    return ResearchDelegationCoordinator(agents)


def get_preview_features_use_case():
    # Lazy: feature engineering is only needed by the preview task.
    from src.application.use_cases.models.feature_engineering import (
        PreviewFeaturesUseCase,
    )

    return PreviewFeaturesUseCase()
