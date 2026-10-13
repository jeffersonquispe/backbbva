from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import src.infrastructure.workflows.celery.alert_review_workflow as workflow_module
import src.infrastructure.workflows.celery.factories as factories_module
from src.application.dtos.alert_metrics_dtos import AlertMetricsEventType
from src.application.ports.alert_action_dispatcher_port import (
    AlertActionDispatcher,
    AlertActionDispatchRef,
)
from src.application.ports.alert_port import AlertOrigin, AlertRecord, AlertStatus
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.ports.analyst_decision_documenter_port import (
    AnalystDecisionDocumenter,
    DocumentationDispatchRef,
)
from src.application.ports.analyst_escalation_port import (
    AnalystEscalationDispatcher,
    AnalystEscalationRef,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.application.ports.configuration_port import (
    AgentSettings,
    ConfigurationRecord,
    DeterministicConfig,
    DeterministicRule,
    FilterGroup,
    GeneralSettings,
    InfraSettings,
    ResolutionTag,
    SegmentSettings,
    ShortageBehavior,
    TestSettings,
)
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.modus_operandi_library_port import ModusOperandiPlaybook
from src.application.ports.monitoring_port import WORKFLOW_TOTAL_STEP, MonitoringPort
from src.application.ports.operational_settings_port import (
    AmountTier,
    OperationalSettings,
)
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityRecord,
)
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.application.use_cases.alerts.resolve_analyst_playbook import (
    ResolvedPlaybook,
)
from src.application.use_cases.alerts.route_alert_resolution import (
    ResolutionRouting,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.infrastructure.monitoring.opentelemetry.monitoring import (
    OpenTelemetryMonitoring,
)
from src.infrastructure.workflows.celery.alert_review_workflow import (
    AlertReviewWorkflowRunner,
)

# Same mandatory-field shape as tests/test_application/test_use_cases/
# test_pre_process_alert.py's VALID_PAYLOAD - non-card channel, every
# dotted path pre_process_alert.py's _MANDATORY_FIELD_PATHS requires.
SYNTHETIC_ALERT_PAYLOAD = {
    "eventId": "evt-synth-1",
    "eventType": "paymentRT",
    "eventTime": "2026-08-09T10:00:00Z",
    "customerId": "10264559",
    "accountId": "acct-synth-1",
    "channel": "mobileApp",
    "merchantId": "merch-synth-1",
    "merchantName": "Synthetic Merchant SAS",
    "integrationPoint": "APP",
    "serviceDescription": "Online transfer",
    "msgStatus": "APPROVED",
    "direction": "OUT",
    "msgReason": "none",
    "customerClientCode": "CC-synth-1",
    "object": {
        "triggeredRules": [{"name": "rule1"}],
        "tags": [{"values": ["high_value"]}],
        "triggeredModels": ["model1"],
    },
    "biocatch": {
        "score": 10,
        "ip": "1.2.3.4",
        "muid": "muid-1",
        "customerSessionID": "sess-synth-1",
    },
    "entryMode": {"terminalDataInputModeCapability": "manual"},
    "session": {"sessionId": "sess-synth-1"},
    "counterpartyName": {"fullName": "Jane Synthetic Doe"},
    "amount": {"baseValue": 15_000_000.0},
    "device": {"ipAddress": "5.6.7.8", "userAgentString": "Mozilla/5.0 (synthetic)"},
    "_metadata": {"searchable": {"deviceId": "dev-synth-1"}},
    "personalId": "pid-synth-1",
}


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[UUID, AlertRecord] = {}

    def create(self, alert: AlertRecord) -> AlertRecord:
        self.alerts[alert.id] = alert
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alerts.get(alert_id)

    def update(self, alert_id: UUID, **changes: Any) -> AlertRecord | None:
        alert = self.alerts.get(alert_id)
        if alert is None:
            return None
        updated = dataclasses.replace(
            alert, **{k: v for k, v in changes.items() if v is not None}
        )
        self.alerts[alert_id] = updated
        return updated


class InMemoryAlertSchemaRepository:
    def __init__(self, active: AlertSchemaVersion) -> None:
        self.active = active

    def get_active(self) -> AlertSchemaVersion:
        return self.active

    def list_versions(self) -> list[AlertSchemaVersion]:
        return [self.active]

    def get(self, version: int) -> AlertSchemaVersion | None:
        return self.active if version == self.active.version else None

    def save_draft(self, schema: AlertSchemaVersion) -> AlertSchemaVersion:
        self.active = schema
        return schema

    def update(self, schema: AlertSchemaVersion) -> AlertSchemaVersion:
        self.active = schema
        return schema


def _schema_field(
    field_id: str,
    field: str,
    field_ds_loc: str,
    field_type: AlertSchemaFieldType,
    *,
    is_mandatory: bool = False,
) -> AlertSchemaField:
    return AlertSchemaField(
        id=field_id,
        data_source=AlertSchemaDataSource.ARIC,
        field=field,
        field_ds_loc=field_ds_loc,
        type=field_type,
        is_mandatory=is_mandatory,
    )


SYNTHETIC_ALERT_SCHEMA = AlertSchemaVersion(
    version=1,
    status=AlertSchemaStatus.ACTIVE,
    fields=[
        _schema_field("event-id", "event_id", "eventId", AlertSchemaFieldType.STRING, is_mandatory=True),
        _schema_field("event-time", "event_time", "eventTime", AlertSchemaFieldType.DATETIME, is_mandatory=True),
        _schema_field("event-type", "event_type", "eventType", AlertSchemaFieldType.STRING, is_mandatory=True),
        _schema_field("channel", "channel", "channel", AlertSchemaFieldType.STRING, is_mandatory=True),
        _schema_field("amount", "amount", "amount.baseValue", AlertSchemaFieldType.NUMBER, is_mandatory=True),
        _schema_field("customer-id", "customer_id", "customerId", AlertSchemaFieldType.STRING, is_mandatory=True),
        _schema_field("account-id", "account_id", "accountId", AlertSchemaFieldType.STRING),
        _schema_field("session-id", "session_id", "session.sessionId", AlertSchemaFieldType.STRING),
        _schema_field("rules", "rules", "object.triggeredRules", AlertSchemaFieldType.LIST, is_mandatory=True),
        _schema_field("integration-point", "integration_point", "integrationPoint", AlertSchemaFieldType.STRING, is_mandatory=True),
        _schema_field("ip-channel", "ip_channel", "device.ipAddress", AlertSchemaFieldType.STRING, is_mandatory=True),
        _schema_field("client-code", "client_code", "customerClientCode", AlertSchemaFieldType.STRING, is_mandatory=True),
        _schema_field("reason-code", "reason_code", "msgReason", AlertSchemaFieldType.STRING),
        _schema_field("biocatch-score", "biocatch_score", "biocatch.score", AlertSchemaFieldType.NUMBER),
        _schema_field("counterparty", "counterparty", "counterpartyName.fullName", AlertSchemaFieldType.STRING),
        _schema_field("transaction-id", "transaction_id", "transactionId", AlertSchemaFieldType.STRING),
        _schema_field("biocatch-muid", "biocatch_muid", "biocatch.muid", AlertSchemaFieldType.STRING),
        _schema_field("tags", "tags", "object.tags", AlertSchemaFieldType.LIST),
        _schema_field("triggered-models", "triggered_models", "object.triggeredModels", AlertSchemaFieldType.LIST),
        _schema_field("device-id", "device_id", "_metadata.searchable.deviceId", AlertSchemaFieldType.STRING),
        _schema_field("entry-mode", "entry_mode", "entryMode.terminalDataInputModeCapability", AlertSchemaFieldType.STRING),
        _schema_field("merchant-id", "merchant_id", "merchantId", AlertSchemaFieldType.STRING),
        _schema_field("merchant-name", "merchant_name", "merchantName", AlertSchemaFieldType.STRING),
        _schema_field("description", "description", "serviceDescription", AlertSchemaFieldType.STRING),
        _schema_field("response", "response", "msgStatus", AlertSchemaFieldType.STRING),
        _schema_field("direction", "direction", "direction", AlertSchemaFieldType.STRING),
        _schema_field("user-agent", "user_agent", "device.userAgentString", AlertSchemaFieldType.STRING),
    ],
    field_roles={
        "event_id": "event-id",
        "event_time": "event-time",
        "event_type": "event-type",
        "channel": "channel",
        "entrypoint": "integration-point",
        "amount": "amount",
        "customer_id": "customer-id",
        "account_id": "account-id",
        "session_id": "session-id",
    },
)


class InMemoryAsyncOperationRepository:
    def __init__(self) -> None:
        self.operations: dict[UUID, AsyncOperationRecord] = {}

    def create(self, operation: AsyncOperationRecord) -> AsyncOperationRecord:
        self.operations[operation.id] = operation
        return operation

    def get(self, operation_id: UUID) -> AsyncOperationRecord | None:
        return self.operations.get(operation_id)

    def list(
        self, status: AsyncOperationStatus | None = None, limit: int = 100
    ) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def list_active(self, limit: int = 100) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def update(self, operation_id: UUID, **changes: Any) -> AsyncOperationRecord | None:
        operation = self.operations.get(operation_id)
        if operation is None:
            return None
        updated = dataclasses.replace(
            operation, **{k: v for k, v in changes.items() if v is not None}
        )
        self.operations[operation_id] = updated
        return updated


class InMemoryWorkflowExecutionRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, WorkflowExecutionRecord] = {}

    def create(self, workflow: WorkflowExecutionRecord) -> WorkflowExecutionRecord:
        self.workflows[workflow.id] = workflow
        return workflow

    def get(self, workflow_id: UUID) -> WorkflowExecutionRecord | None:
        return self.workflows.get(workflow_id)

    def update(
        self, workflow_id: UUID, **changes: Any
    ) -> WorkflowExecutionRecord | None:
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            return None
        updated = dataclasses.replace(
            workflow, **{k: v for k, v in changes.items() if v is not None}
        )
        self.workflows[workflow_id] = updated
        return updated


class InMemoryWorkflowStepExecutionRepository:
    def __init__(self) -> None:
        self.steps: dict[UUID, WorkflowStepExecutionRecord] = {}

    def create(self, step: WorkflowStepExecutionRecord) -> WorkflowStepExecutionRecord:
        self.steps[step.id] = step
        return step

    def list_by_workflow(
        self, workflow_execution_id: UUID
    ) -> list[WorkflowStepExecutionRecord]:
        return [
            step
            for step in self.steps.values()
            if step.workflow_execution_id == workflow_execution_id
        ]

    def update(
        self, workflow_execution_id: UUID, step_id: UUID, **changes: Any
    ) -> WorkflowStepExecutionRecord | None:
        step = self.steps.get(step_id)
        if step is None:
            return None
        updated = dataclasses.replace(
            step, **{k: v for k, v in changes.items() if v is not None}
        )
        self.steps[step_id] = updated
        return updated


class InMemoryConfigurationRepository:
    """Only get_active() is implemented - the only method
    _resolve_configuration calls on the no-ref (production) path."""

    def __init__(self, active: ConfigurationRecord | None) -> None:
        self._active = active

    def get_active(self) -> ConfigurationRecord | None:
        return self._active


class InMemoryOperationalSettingsRepository:
    def __init__(self, settings: OperationalSettings) -> None:
        self.settings = settings

    def get(self) -> OperationalSettings:
        return self.settings


class PassthroughRouteAlertResolutionUseCase:
    """Every resource the analyst picks is available."""

    def execute(self, *, alert_id, decision, playbook):
        return ResolutionRouting(decision=decision)


class ScriptedResolveAnalystPlaybookUseCase:
    def __init__(self, resolved: ResolvedPlaybook | None) -> None:
        self._resolved = resolved

    def execute(self, query, *, vector_store_instance_id):
        return self._resolved


_ARIA_PLAYBOOK = ResolvedPlaybook(
    modus_operandi_id="mo-ato",
    modus_operandi_title="Account takeover",
    playbook=ModusOperandiPlaybook(
        strategy="Verificar dispositivo y contactar al cliente.",
        resolution=ShortageBehavior(resolution_tag=ResolutionTag.HANDLE_BY_ARIA),
    ),
)


class RecordingMetricsEvents:
    """Stands in for RecordAlertMetricsEvent: records every event input."""

    def __init__(self) -> None:
        self.events: list = []

    def execute(self, input):
        self.events.append(input)
        return None


@pytest.fixture(autouse=True)
def metrics_events(monkeypatch) -> RecordingMetricsEvents:
    recorder = RecordingMetricsEvents()
    monkeypatch.setattr(
        workflow_module, "get_record_alert_metrics_event_use_case", lambda: recorder
    )
    return recorder


class RecordingStepMetrics:
    """Stands in for RecordWorkflowStepMetrics: records every input."""

    def __init__(self) -> None:
        self.inputs: list = []

    def execute(self, input):
        self.inputs.append(input)
        return None


class RecordingReasoningEvaluationDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    def dispatch(self, alert_id, workflow_execution_id):
        self.calls.append((alert_id, workflow_execution_id))
        return None


@pytest.fixture(autouse=True)
def step_metrics(monkeypatch) -> RecordingStepMetrics:
    recorder = RecordingStepMetrics()
    monkeypatch.setattr(
        workflow_module, "get_record_workflow_step_metrics_use_case", lambda: recorder
    )
    return recorder


@pytest.fixture(autouse=True)
def evaluation_dispatches(monkeypatch) -> RecordingReasoningEvaluationDispatcher:
    dispatcher = RecordingReasoningEvaluationDispatcher()
    monkeypatch.setattr(
        workflow_module, "get_reasoning_evaluation_dispatcher", lambda: dispatcher
    )
    return dispatcher


@pytest.fixture(autouse=True)
def _operations_defaults(monkeypatch):
    # Agent on, every resource available, no modus operandi playbook -
    # individual tests override what they exercise.
    monkeypatch.setattr(
        workflow_module,
        "get_operational_settings_repository",
        lambda: InMemoryOperationalSettingsRepository(OperationalSettings()),
    )
    monkeypatch.setattr(
        workflow_module,
        "get_route_alert_resolution_use_case",
        PassthroughRouteAlertResolutionUseCase,
    )
    monkeypatch.setattr(
        factories_module,
        "get_resolve_analyst_playbook_use_case",
        lambda: ScriptedResolveAnalystPlaybookUseCase(None),
    )


class InMemoryOperationsCapacityRepository:
    def __init__(self, capacity: OperationsCapacityRecord) -> None:
        self._capacity = capacity

    def get_capacity(self) -> OperationsCapacityRecord:
        return self._capacity


class RecordingAlertActionDispatcher(AlertActionDispatcher):
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, str | None]] = []

    def dispatch(
        self, action: str, alert_id: UUID, content: str | None = None
    ) -> AlertActionDispatchRef:
        self.calls.append((action, alert_id, content))
        return AlertActionDispatchRef(backend="celery", external_id="fake-action-1")


class RecordingAnalystEscalationDispatcher(AnalystEscalationDispatcher):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID,
        event_id: str,
        session_id: str | None,
        reason: str,
    ) -> AnalystEscalationRef:
        self.calls.append(
            {
                "alert_id": alert_id,
                "workflow_execution_id": workflow_execution_id,
                "event_id": event_id,
                "session_id": session_id,
                "reason": reason,
            }
        )
        return AnalystEscalationRef(backend="celery", external_id="fake-escalation-1")


class RecordingAnalystDecisionDocumenter(AnalystDecisionDocumenter):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID,
        steps: dict[str, dict[str, Any]],
    ) -> DocumentationDispatchRef:
        self.calls.append(
            {
                "alert_id": alert_id,
                "workflow_execution_id": workflow_execution_id,
                "steps": steps,
            }
        )
        return DocumentationDispatchRef(backend="celery", external_id="fake-doc-1")


# One canned final answer per ReAct/JSON operation_name - each use case's
# system prompt asks for a single well-formed "Final Answer:"/JSON turn, so
# the fake never needs to emit a Thought/Action step to stay deterministic.
_LLM_RESPONSES: dict[str, str] = {
    "user_profile": (
        "Synthetic user profile: long-standing customer, no adverse "
        "behavioral signals on record."
    ),
    "transaction_profile": (
        "Synthetic transaction profile: amount and channel are within "
        "this account's historical norms."
    ),
    "transactional_profile": (
        "Synthetic transactional profile: consistent with the customer's "
        "prior 90-day transaction pattern."
    ),
    "detector": (
        "Thought: initial signals warrant a closer look.\n"
        'Final Answer: {"is_fraud": "fraud", "fraud_classification": '
        '"unknown", "reasoning": "Enough anomalies to send this to '
        'classification."}'
    ),
    "detector_adversarial": (
        "Thought: detector's call holds up on independent review.\n"
        'Final Answer: {"has_issues": false, "feedback": "", '
        '"weak_points": [], "reasoning": "Detector correctly flagged this '
        'for deeper investigation."}'
    ),
    "classification": (
        "Thought: device and session signals diverge from prior sessions.\n"
        'Final Answer: {"is_fraud": "fraud", "fraud_classification": '
        '"account_takeover", "reasoning": "Session and device fingerprint '
        'are inconsistent with the known customer profile."}'
    ),
    "adversarial": (
        "Thought: independently checked the analyst's evidence.\n"
        'Final Answer: {"has_issues": false, "feedback": "", '
        '"weak_points": [], "reasoning": "Classification is well '
        'supported by the available evidence."}'
    ),
    "analyst": (
        '{"decision": "bidi", "reasoning": "Moderate risk and bidi '
        'channel has available capacity - route for verification."}'
    ),
}


class FakeLLMUnitOfWork(LLMUnitOfWork):
    def __init__(self, operation_name: str) -> None:
        self._operation_name = operation_name

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        return LLMInvocationResult(
            content=_LLM_RESPONSES[self._operation_name],
            model="fake-model",
        )


class FakeLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        self.calls.append(operation_name)
        return FakeLLMUnitOfWork(operation_name)


class RecordingOpenTelemetryMonitoring(OpenTelemetryMonitoring):
    """Real span adapter (in-memory exporter) that also records the explicit
    metric calls the runner makes."""

    def __init__(self, tracer) -> None:
        super().__init__(tracer)
        self.workflow_durations: list[tuple[str, str, float]] = []
        self.research_calls: list[tuple[str, str]] = []

    def record_workflow_duration(self, step, outcome, duration_seconds) -> None:
        self.workflow_durations.append((step, outcome, duration_seconds))

    def record_research_call(self, source, outcome) -> None:
        self.research_calls.append((source, str(outcome)))


def _build_in_memory_monitoring() -> tuple[MonitoringPort, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return RecordingOpenTelemetryMonitoring(provider.get_tracer("test")), exporter


@pytest.fixture(autouse=True)
def in_memory_monitoring(monkeypatch):
    # The runner looks up factories.get_monitoring() itself: never let a
    # test reach the real (global) OTel provider. Tests that patch it again
    # (e.g. _run_full_pipeline) simply override this one.
    monitoring, exporter = _build_in_memory_monitoring()
    monkeypatch.setattr(factories_module, "get_monitoring", lambda: monitoring)
    return monitoring, exporter


@pytest.fixture(autouse=True)
def in_memory_alert_schema_repository(monkeypatch):
    repository = InMemoryAlertSchemaRepository(SYNTHETIC_ALERT_SCHEMA)
    monkeypatch.setattr(factories_module, "get_alert_schema_repository", lambda: repository)
    return repository


def _run_full_pipeline(monkeypatch, resolved: ResolvedPlaybook | None):
    now = datetime.now(UTC)

    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    capacity = InMemoryOperationsCapacityRepository(
        OperationsCapacityRecord(
            analysts=ChannelCapacity(available=3, status="available"),
            voicebot=ChannelCapacity(available=2, status="available"),
            bidi=ChannelCapacity(available=1, status="available"),
            updated_at=now,
        )
    )
    action_dispatcher = RecordingAlertActionDispatcher()
    escalation_dispatcher = RecordingAnalystEscalationDispatcher()
    documenter_dispatcher = RecordingAnalystDecisionDocumenter()
    llm_factory = FakeLLMUnitOfWorkFactory()
    # Real step use cases get a real MonitoringPort instance. FakeLLMUnitOfWork
    # never calls monitoring.start() (unlike the real Langchain adapter), so
    # the spans here are the runner's own workflow/step spans (T2) plus the
    # step use cases' (escalation, action, ...).
    monitoring, span_exporter = _build_in_memory_monitoring()

    # AlertReviewWorkflowRunner and the per-step _run_* functions call these
    # factory functions by the name each imported into its own module
    # namespace, so patches must target the module that does the calling:
    # workflow_module for repos/dispatchers it calls directly, factories_module
    # for adapters only ever looked up from inside a get_*_use_case() factory.
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(
        workflow_module, "get_async_operation_repository", lambda: operations
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_execution_repository", lambda: workflows
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_step_execution_repository", lambda: steps
    )
    monkeypatch.setattr(
        factories_module, "get_live_operations_capacity", lambda: capacity
    )
    monkeypatch.setattr(
        factories_module,
        "get_resolve_analyst_playbook_use_case",
        lambda: ScriptedResolveAnalystPlaybookUseCase(resolved),
    )
    monkeypatch.setattr(
        workflow_module, "get_alert_action_dispatcher", lambda: action_dispatcher
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_escalation_dispatcher",
        lambda: escalation_dispatcher,
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_decision_documenter",
        lambda: documenter_dispatcher,
    )
    monkeypatch.setattr(
        factories_module, "get_llm_unit_of_work_factory", lambda: llm_factory
    )
    monkeypatch.setattr(factories_module, "get_monitoring", lambda: monitoring)

    alert_id = uuid.uuid4()
    async_operation_id = uuid.uuid4()
    workflow_id = uuid.uuid4()

    alerts.create(
        AlertRecord(
            id=alert_id,
            event_id=SYNTHETIC_ALERT_PAYLOAD["eventId"],
            event_type=SYNTHETIC_ALERT_PAYLOAD["eventType"],
            status=AlertStatus.PROCESSING,
            created_at=now,
            updated_at=now,
            schema_version=1,
            input={
                "channel": "mobileApp",
                "integration_point": "mobile",
                "amount": SYNTHETIC_ALERT_PAYLOAD["amount"]["baseValue"],
            },
            customer_id=SYNTHETIC_ALERT_PAYLOAD["customerId"],
            async_operation_id=async_operation_id,
            workflow_execution_id=workflow_id,
        )
    )
    operations.create(
        AsyncOperationRecord(
            id=async_operation_id,
            operation_type="alert_review_workflow",
            status=AsyncOperationStatus.DISPATCHED,
            payload={"alert_id": str(alert_id)},
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
    )
    workflows.create(
        WorkflowExecutionRecord(
            id=workflow_id,
            alert_id=alert_id,
            async_operation_id=async_operation_id,
            workflow_name="alert_review",
            status=WorkflowStatus.PENDING,
            input={"alert_payload": SYNTHETIC_ALERT_PAYLOAD},
            output=None,
            error=None,
            current_step=None,
            feedback_iterations=0,
            max_feedback_iterations=2,
            created_at=now,
            updated_at=now,
        )
    )

    result = AlertReviewWorkflowRunner().run(workflow_id)
    return dict(
        result=result,
        alert_id=alert_id,
        workflow_id=workflow_id,
        async_operation_id=async_operation_id,
        alerts=alerts,
        operations=operations,
        workflows=workflows,
        steps=steps,
        action_dispatcher=action_dispatcher,
        escalation_dispatcher=escalation_dispatcher,
        documenter_dispatcher=documenter_dispatcher,
        llm_factory=llm_factory,
        monitoring=monitoring,
        span_exporter=span_exporter,
    )


def test_alert_review_workflow_runs_full_pipeline_on_synthetic_alert(monkeypatch):
    run = _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)
    result, alert_id, workflow_id = run["result"], run["alert_id"], run["workflow_id"]
    async_operation_id = run["async_operation_id"]
    alerts, operations, workflows, steps = (
        run["alerts"], run["operations"], run["workflows"], run["steps"]
    )
    action_dispatcher = run["action_dispatcher"]
    escalation_dispatcher = run["escalation_dispatcher"]
    documenter_dispatcher = run["documenter_dispatcher"]
    llm_factory = run["llm_factory"]

    assert result == {"status": "ok", "workflow_execution_id": str(workflow_id)}

    finished_workflow = workflows.get(workflow_id)
    assert finished_workflow is not None
    assert finished_workflow.status == WorkflowStatus.SUCCEEDED
    assert finished_workflow.current_step == "post_process"
    assert finished_workflow.output is not None
    assert finished_workflow.output["resolution_path"] == "bidi"

    finished_alert = alerts.get(alert_id)
    assert finished_alert is not None
    assert finished_alert.status == AlertStatus.CLOSED

    finished_operation = operations.get(async_operation_id)
    assert finished_operation is not None
    assert finished_operation.status == AsyncOperationStatus.SUCCEEDED

    recorded_steps = {s.step_name: s for s in steps.list_by_workflow(workflow_id)}
    assert set(recorded_steps) == {
        "pre_process",
        "deterministic",
        "profiling",
        "detector",
        "detector_adversarial",
        "classification",
        "adversarial",
        "analyst",
        "executor",
        "post_process",
    }
    assert all(
        step.status == WorkflowStepStatus.SUCCEEDED
        for step in recorded_steps.values()
    )
    assert recorded_steps["classification"].output["fraud_classification"] == (
        "account_takeover"
    )
    assert recorded_steps["analyst"].output["decision"] == "bidi"
    assert recorded_steps["analyst"].output["modus_operandi_id"] == "mo-ato"

    # No active configuration/segment in this synthetic run, so there's no
    # executor.aric_marking prompt to generate a comment from - content
    # stays None (see alert_review_workflow.py's _run_executor).
    assert action_dispatcher.calls == [("bidi", alert_id, None)]
    assert escalation_dispatcher.calls == []
    assert len(documenter_dispatcher.calls) == 1
    assert set(documenter_dispatcher.calls[0]["steps"]) == {
        "pre_process",
        "profiling",
        "classification",
        "adversarial",
        "analyst",
    }

    assert llm_factory.calls == [
        "user_profile",
        "transaction_profile",
        "transactional_profile",
        "detector",
        "detector_adversarial",
        "classification",
        "adversarial",
        "analyst",
    ]


def test_alert_review_workflow_escalates_without_playbook_and_leaves_alert_escalated(
    monkeypatch,
):
    run = _run_full_pipeline(monkeypatch, resolved=None)

    assert run["result"]["status"] == "ok"
    recorded_steps = {
        s.step_name: s for s in run["steps"].list_by_workflow(run["workflow_id"])
    }
    assert recorded_steps["analyst"].output["decision"] == "scale_to_analyst"
    assert recorded_steps["analyst"].output["playbook"] is None
    assert run["escalation_dispatcher"].calls != []
    assert run["action_dispatcher"].calls == []
    # No playbook -> the LLM is never asked to decide.
    assert "analyst" not in run["llm_factory"].calls
    # Waits in the analyst queue until a human resolves it.
    assert run["alerts"].get(run["alert_id"]).status == AlertStatus.ESCALATED


def _seed_pending_workflow(alerts, operations, workflows, input: dict[str, Any]):
    now = datetime.now(UTC)
    alert_id, operation_id, workflow_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    alerts.create(
        AlertRecord(
            id=alert_id,
            event_id="evt-1",
            event_type="paymentRT",
            status=AlertStatus.PROCESSING,
            created_at=now,
            updated_at=now,
        )
    )
    operations.create(
        AsyncOperationRecord(
            id=operation_id,
            operation_type="alert_review_workflow",
            status=AsyncOperationStatus.DISPATCHED,
            payload={"alert_id": str(alert_id)},
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
    )
    workflows.create(
        WorkflowExecutionRecord(
            id=workflow_id,
            alert_id=alert_id,
            async_operation_id=operation_id,
            workflow_name="alert_review",
            status=WorkflowStatus.PENDING,
            input=input,
            output=None,
            error=None,
            current_step=None,
            feedback_iterations=0,
            max_feedback_iterations=1,
            created_at=now,
            updated_at=now,
        )
    )
    return alert_id, operation_id, workflow_id


@pytest.mark.parametrize("origin", [AlertOrigin.SIMULATOR, AlertOrigin.PRODUCTION])
def test_agent_off_skips_simulator_and_production_alerts(monkeypatch, caplog, origin):
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(workflow_module, "get_async_operation_repository", lambda: operations)
    monkeypatch.setattr(workflow_module, "get_workflow_execution_repository", lambda: workflows)
    monkeypatch.setattr(workflow_module, "get_workflow_step_execution_repository", lambda: steps)
    monkeypatch.setattr(
        workflow_module,
        "get_operational_settings_repository",
        lambda: InMemoryOperationalSettingsRepository(
            OperationalSettings(agent_enabled=False)
        ),
    )
    alert_id, operation_id, workflow_id = _seed_pending_workflow(
        alerts,
        operations,
        workflows,
        {"alert_payload": SYNTHETIC_ALERT_PAYLOAD, "origin": origin.value},
    )

    with caplog.at_level("WARNING", logger=workflow_module.__name__):
        result = AlertReviewWorkflowRunner().run(workflow_id)

    assert result == {"status": "skipped", "workflow_execution_id": str(workflow_id)}
    workflow = workflows.get(workflow_id)
    assert workflow.status == WorkflowStatus.SUCCEEDED
    assert workflow.output["status"] == "skipped"
    assert workflow.output["origin"] == origin.value
    assert alerts.get(alert_id).status == AlertStatus.SKIPPED
    assert operations.get(operation_id).status == AsyncOperationStatus.SUCCEEDED
    # Nothing ran.
    assert steps.list_by_workflow(workflow_id) == []
    assert str(alert_id) in caplog.text and origin.value in caplog.text


@pytest.mark.parametrize("origin", [None, "manual", "test_run"])
def test_agent_off_still_processes_manual_and_test_run_alerts(monkeypatch, origin):
    monkeypatch.setattr(
        workflow_module,
        "get_operational_settings_repository",
        lambda: InMemoryOperationalSettingsRepository(
            OperationalSettings(agent_enabled=False)
        ),
    )
    input: dict[str, Any] = {"alert_payload": SYNTHETIC_ALERT_PAYLOAD}
    if origin is not None:
        input["origin"] = origin

    # Only the gate matters here: the run must get past it and start the
    # first step, which is stubbed to fail fast.
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(workflow_module, "get_async_operation_repository", lambda: operations)
    monkeypatch.setattr(workflow_module, "get_workflow_execution_repository", lambda: workflows)
    monkeypatch.setattr(workflow_module, "get_workflow_step_execution_repository", lambda: steps)
    _, _, workflow_id = _seed_pending_workflow(alerts, operations, workflows, input)
    monkeypatch.setattr(
        workflow_module,
        "_execute_placeholder_step",
        lambda step_name, context: (_ for _ in ()).throw(RuntimeError("reached")),
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_escalation_dispatcher",
        RecordingAnalystEscalationDispatcher,
    )

    with pytest.raises(RuntimeError, match="reached"):
        AlertReviewWorkflowRunner().run(workflow_id)

    assert steps.list_by_workflow(workflow_id)[0].step_name == "pre_process"


def test_alert_review_workflow_discards_alert_on_deterministic_rule_match(
    monkeypatch, metrics_events
):
    now = datetime.now(UTC)

    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    action_dispatcher = RecordingAlertActionDispatcher()
    escalation_dispatcher = RecordingAnalystEscalationDispatcher()
    documenter_dispatcher = RecordingAnalystDecisionDocumenter()
    llm_factory = FakeLLMUnitOfWorkFactory()
    monitoring, exporter = _build_in_memory_monitoring()

    # A single enabled segment with an empty filter (vacuously matches any
    # alert - see resolve_alert_segment.py) and one deterministic rule that
    # matches SYNTHETIC_ALERT_PAYLOAD's amount (15_000_000).
    segment = SegmentSettings(
        enabled=True,
        filter=FilterGroup(id="root"),
        agent=AgentSettings(
            deterministic=DeterministicConfig(
                rules=[
                    DeterministicRule(
                        id="high-amount",
                        variable="amount",
                        comparison="gt",
                        values=["1000000"],
                        decision="risk",
                        aric_action="hard_block",
                    )
                ]
            )
        ),
    )
    config_repo = InMemoryConfigurationRepository(
        ConfigurationRecord(
            configuration_id="cfg-discard",
            version=1,
            name="cfg-discard-v1",
            description="",
            active=True,
            general=GeneralSettings(),
            infra=InfraSettings(),
            test=TestSettings(),
            created_at=now,
            updated_at=now,
            segments={"canales_digitales": segment},
        )
    )

    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(
        workflow_module, "get_async_operation_repository", lambda: operations
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_execution_repository", lambda: workflows
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_step_execution_repository", lambda: steps
    )
    monkeypatch.setattr(
        workflow_module, "get_configuration_repository", lambda: config_repo
    )
    monkeypatch.setattr(
        workflow_module, "get_alert_action_dispatcher", lambda: action_dispatcher
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_escalation_dispatcher",
        lambda: escalation_dispatcher,
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_decision_documenter",
        lambda: documenter_dispatcher,
    )
    monkeypatch.setattr(
        factories_module, "get_llm_unit_of_work_factory", lambda: llm_factory
    )
    monkeypatch.setattr(factories_module, "get_monitoring", lambda: monitoring)

    alert_id = uuid.uuid4()
    async_operation_id = uuid.uuid4()
    workflow_id = uuid.uuid4()

    alerts.create(
        AlertRecord(
            id=alert_id,
            event_id=SYNTHETIC_ALERT_PAYLOAD["eventId"],
            event_type=SYNTHETIC_ALERT_PAYLOAD["eventType"],
            status=AlertStatus.PROCESSING,
            created_at=now,
            updated_at=now,
            schema_version=1,
            input={
                "channel": "mobileApp",
                "integration_point": "mobile",
                "amount": SYNTHETIC_ALERT_PAYLOAD["amount"]["baseValue"],
            },
            customer_id=SYNTHETIC_ALERT_PAYLOAD["customerId"],
            async_operation_id=async_operation_id,
            workflow_execution_id=workflow_id,
        )
    )
    operations.create(
        AsyncOperationRecord(
            id=async_operation_id,
            operation_type="alert_review_workflow",
            status=AsyncOperationStatus.DISPATCHED,
            payload={"alert_id": str(alert_id)},
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
    )
    workflows.create(
        WorkflowExecutionRecord(
            id=workflow_id,
            alert_id=alert_id,
            async_operation_id=async_operation_id,
            workflow_name="alert_review",
            status=WorkflowStatus.PENDING,
            input={"alert_payload": SYNTHETIC_ALERT_PAYLOAD},
            output=None,
            error=None,
            current_step=None,
            feedback_iterations=0,
            max_feedback_iterations=2,
            created_at=now,
            updated_at=now,
        )
    )

    result = AlertReviewWorkflowRunner().run(workflow_id)

    assert result == {"status": "ok", "workflow_execution_id": str(workflow_id)}

    finished_workflow = workflows.get(workflow_id)
    assert finished_workflow is not None
    assert finished_workflow.status == WorkflowStatus.SUCCEEDED
    assert finished_workflow.current_step == "deterministic"
    # C4: a discard is recorded as ARIA's no_fraud decision.
    finished_events = [
        e for e in metrics_events.events
        if e.event_type == AlertMetricsEventType.WORKFLOW_FINISHED
    ]
    assert [(e.status, e.executed_action) for e in finished_events] == [
        (AlertStatus.CLOSED, "discarded")
    ]
    assert finished_workflow.output is not None
    assert finished_workflow.output["resolution_path"] == "discarded_deterministic"

    finished_alert = alerts.get(alert_id)
    assert finished_alert is not None
    assert finished_alert.status == AlertStatus.CLOSED
    # The configuration resolved after pre_process is stored on the alert.
    assert finished_alert.configuration_id == "cfg-discard"
    assert finished_alert.configuration_version == 1

    # Only pre_process and deterministic ran - everything from profiling
    # onward was skipped.
    recorded_steps = {s.step_name for s in steps.list_by_workflow(workflow_id)}
    assert recorded_steps == {"pre_process", "deterministic"}

    assert action_dispatcher.calls == []
    assert escalation_dispatcher.calls == []
    assert documenter_dispatcher.calls == []
    assert llm_factory.calls == []

    spans = exporter.get_finished_spans()
    discard_spans = [s for s in spans if s.name == "discard_alert"]
    assert len(discard_spans) == 1


class _NotFraudDetectorLLMUnitOfWork(LLMUnitOfWork):
    """Same canned responses as _LLM_RESPONSES, except "detector" - lets
    this one test exercise the not_fraud gate without touching the shared
    dict the full-pipeline test above depends on."""

    def __init__(self, operation_name: str) -> None:
        self._operation_name = operation_name

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        if self._operation_name == "detector":
            return LLMInvocationResult(
                content=(
                    "Thought: nothing unusual here.\n"
                    'Final Answer: {"is_fraud": "not_fraud", '
                    '"fraud_classification": "unknown", "reasoning": '
                    '"No anomalies found."}'
                ),
                model="fake-model",
            )
        return LLMInvocationResult(
            content=_LLM_RESPONSES[self._operation_name], model="fake-model"
        )


class _NotFraudLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        self.calls.append(operation_name)
        return _NotFraudDetectorLLMUnitOfWork(operation_name)


def test_alert_review_workflow_skips_to_pass_when_detector_finds_no_fraud(monkeypatch):
    now = datetime.now(UTC)

    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    action_dispatcher = RecordingAlertActionDispatcher()
    escalation_dispatcher = RecordingAnalystEscalationDispatcher()
    documenter_dispatcher = RecordingAnalystDecisionDocumenter()
    llm_factory = _NotFraudLLMUnitOfWorkFactory()
    monitoring, _ = _build_in_memory_monitoring()

    # No deterministic rules on this segment - just enabled, so the alert
    # reaches profiling and detector normally.
    segment = SegmentSettings(enabled=True, filter=FilterGroup(id="root"))
    config_repo = InMemoryConfigurationRepository(
        ConfigurationRecord(
            configuration_id="cfg-not-fraud",
            version=1,
            name="cfg-not-fraud-v1",
            description="",
            active=True,
            general=GeneralSettings(),
            infra=InfraSettings(),
            test=TestSettings(),
            created_at=now,
            updated_at=now,
            segments={"canales_digitales": segment},
        )
    )

    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(
        workflow_module, "get_async_operation_repository", lambda: operations
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_execution_repository", lambda: workflows
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_step_execution_repository", lambda: steps
    )
    monkeypatch.setattr(
        workflow_module, "get_configuration_repository", lambda: config_repo
    )
    monkeypatch.setattr(
        workflow_module, "get_alert_action_dispatcher", lambda: action_dispatcher
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_escalation_dispatcher",
        lambda: escalation_dispatcher,
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_decision_documenter",
        lambda: documenter_dispatcher,
    )
    monkeypatch.setattr(
        factories_module, "get_llm_unit_of_work_factory", lambda: llm_factory
    )
    monkeypatch.setattr(factories_module, "get_monitoring", lambda: monitoring)

    alert_id = uuid.uuid4()
    async_operation_id = uuid.uuid4()
    workflow_id = uuid.uuid4()

    alerts.create(
        AlertRecord(
            id=alert_id,
            event_id=SYNTHETIC_ALERT_PAYLOAD["eventId"],
            event_type=SYNTHETIC_ALERT_PAYLOAD["eventType"],
            input=SYNTHETIC_ALERT_PAYLOAD,
            status=AlertStatus.PROCESSING,
            created_at=now,
            updated_at=now,
            customer_id=SYNTHETIC_ALERT_PAYLOAD["customerId"],
            async_operation_id=async_operation_id,
            workflow_execution_id=workflow_id,
        )
    )
    operations.create(
        AsyncOperationRecord(
            id=async_operation_id,
            operation_type="alert_review_workflow",
            status=AsyncOperationStatus.DISPATCHED,
            payload={"alert_id": str(alert_id)},
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
    )
    workflows.create(
        WorkflowExecutionRecord(
            id=workflow_id,
            alert_id=alert_id,
            async_operation_id=async_operation_id,
            workflow_name="alert_review",
            status=WorkflowStatus.PENDING,
            input={"alert_payload": SYNTHETIC_ALERT_PAYLOAD},
            output=None,
            error=None,
            current_step=None,
            feedback_iterations=0,
            max_feedback_iterations=2,
            created_at=now,
            updated_at=now,
        )
    )

    result = AlertReviewWorkflowRunner().run(workflow_id)

    assert result == {"status": "ok", "workflow_execution_id": str(workflow_id)}

    finished_workflow = workflows.get(workflow_id)
    assert finished_workflow is not None
    assert finished_workflow.status == WorkflowStatus.SUCCEEDED
    assert finished_workflow.current_step == "post_process"
    assert finished_workflow.output is not None
    assert finished_workflow.output["resolution_path"] == "pass"

    finished_alert = alerts.get(alert_id)
    assert finished_alert is not None
    assert finished_alert.status == AlertStatus.CLOSED

    # detector_adversarial/classification/adversarial/analyst were all
    # skipped - only pre_process, deterministic, profiling, detector,
    # executor and post_process actually ran.
    recorded_steps = {s.step_name for s in steps.list_by_workflow(workflow_id)}
    assert recorded_steps == {
        "pre_process",
        "deterministic",
        "profiling",
        "detector",
        "executor",
        "post_process",
    }
    assert llm_factory.calls == [
        "user_profile",
        "transaction_profile",
        "transactional_profile",
        "detector",
    ]
    assert action_dispatcher.calls == []
    assert escalation_dispatcher.calls == []
    assert documenter_dispatcher.calls == []


# --- C4: metrics events at the workflow's hook points -----------------------------


def _metrics_summary(metrics_events):
    return [
        (e.event_type, e.status, e.executed_action) for e in metrics_events.events
    ]


def test_metrics_events_on_full_pipeline(monkeypatch, metrics_events):
    run = _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)

    assert _metrics_summary(metrics_events) == [
        (AlertMetricsEventType.PRE_PROCESSED, None, None),
        (AlertMetricsEventType.WORKFLOW_FINISHED, AlertStatus.CLOSED, "bidi"),
    ]
    assert all(e.alert_id == run["alert_id"] for e in metrics_events.events)


def test_metrics_events_on_escalation(monkeypatch, metrics_events):
    _run_full_pipeline(monkeypatch, resolved=None)

    assert _metrics_summary(metrics_events)[-1] == (
        AlertMetricsEventType.WORKFLOW_FINISHED,
        AlertStatus.ESCALATED,
        "scale_to_analyst",
    )


def test_metrics_event_on_skip(monkeypatch, metrics_events):
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(workflow_module, "get_async_operation_repository", lambda: operations)
    monkeypatch.setattr(workflow_module, "get_workflow_execution_repository", lambda: workflows)
    monkeypatch.setattr(
        workflow_module,
        "get_operational_settings_repository",
        lambda: InMemoryOperationalSettingsRepository(OperationalSettings(agent_enabled=False)),
    )
    _, _, workflow_id = _seed_pending_workflow(
        alerts, operations, workflows, {"alert_payload": SYNTHETIC_ALERT_PAYLOAD, "origin": "simulator"}
    )

    AlertReviewWorkflowRunner().run(workflow_id)

    assert _metrics_summary(metrics_events) == [
        (AlertMetricsEventType.WORKFLOW_FINISHED, AlertStatus.SKIPPED, None)
    ]


def test_metrics_events_on_failure_then_escalation(monkeypatch, metrics_events):
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(workflow_module, "get_async_operation_repository", lambda: operations)
    monkeypatch.setattr(workflow_module, "get_workflow_execution_repository", lambda: workflows)
    monkeypatch.setattr(workflow_module, "get_workflow_step_execution_repository", lambda: steps)
    monkeypatch.setattr(
        workflow_module, "get_analyst_escalation_dispatcher", RecordingAnalystEscalationDispatcher
    )
    # Empty payload: pre_process fails on missing mandatory data.
    _, _, workflow_id = _seed_pending_workflow(
        alerts, operations, workflows, {"alert_payload": {}}
    )

    with pytest.raises(Exception):
        AlertReviewWorkflowRunner().run(workflow_id)

    assert _metrics_summary(metrics_events) == [
        (AlertMetricsEventType.WORKFLOW_FINISHED, AlertStatus.FAILED, None),
        (AlertMetricsEventType.WORKFLOW_FINISHED, AlertStatus.ESCALATED, "scale_to_analyst"),
    ]


def test_metrics_failure_never_fails_the_workflow(monkeypatch):
    class Exploding:
        def execute(self, input):
            raise RuntimeError("dynamodb down")

    monkeypatch.setattr(
        workflow_module, "get_record_alert_metrics_event_use_case", lambda: Exploding()
    )
    run = _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)

    assert run["result"]["status"] == "ok"
    assert run["alerts"].get(run["alert_id"]).status == AlertStatus.CLOSED


# --- R8: technical metrics from the run's step records ---------------------------


class InMemoryMarkedRollupRepository:
    """MetricsRollupRepository fake for apply_once: rows summed per key and
    hour, markers kept in a set (a known marker writes nothing)."""

    def __init__(self) -> None:
        self.markers: set[tuple[str, str]] = set()
        self.rows: dict = {}

    def apply_once(self, deltas, marker) -> bool:
        if (marker.scope, marker.key) in self.markers:
            return False
        self.markers.add((marker.scope, marker.key))
        for delta in deltas:
            slots = self.rows.setdefault(delta.key, {})
            for name, value in delta.measures.items():
                hours = slots.setdefault(name, [0.0] * 24)
                hours[delta.hour] += value
        return True

    def total(self, data_type, level, measure) -> float:
        return sum(
            sum(slots.get(measure, [0.0] * 24))
            for key, slots in self.rows.items()
            if key.data_type == data_type and key.level == level
        )


def test_step_metrics_recorded_once_per_successful_run(monkeypatch, step_metrics):
    run = _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)

    assert len(step_metrics.inputs) == 1
    recorded = step_metrics.inputs[0]
    assert recorded.alert_id == run["alert_id"]
    assert recorded.workflow_execution_id == run["workflow_id"]
    assert {"detector", "classification", "adversarial", "analyst"} <= set(
        recorded.step_models
    )
    assert "pre_process" not in recorded.step_models


def test_step_metrics_recorded_on_failure(monkeypatch, step_metrics):
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(workflow_module, "get_async_operation_repository", lambda: operations)
    monkeypatch.setattr(workflow_module, "get_workflow_execution_repository", lambda: workflows)
    monkeypatch.setattr(workflow_module, "get_workflow_step_execution_repository", lambda: steps)
    monkeypatch.setattr(
        workflow_module, "get_analyst_escalation_dispatcher", RecordingAnalystEscalationDispatcher
    )
    _, _, workflow_id = _seed_pending_workflow(alerts, operations, workflows, {"alert_payload": {}})

    with pytest.raises(Exception):
        AlertReviewWorkflowRunner().run(workflow_id)

    assert [i.workflow_execution_id for i in step_metrics.inputs] == [workflow_id]


def test_step_metrics_rows_and_tokens_match_token_usage(monkeypatch):
    from src.application.dtos.technical_metrics_dtos import (
        RecordWorkflowStepMetricsInput,
    )
    from src.application.ports.metrics_rollup_port import MetricsDataType, RollupLevel
    from src.application.use_cases.metrics.record_workflow_step_metrics import (
        RecordWorkflowStepMetrics,
    )
    from src.application.use_cases.test_runs.token_usage import sum_step_tokens

    def invoke_with_usage(self, messages):
        return LLMInvocationResult(
            content=_LLM_RESPONSES[self._operation_name],
            model="fake-model",
            input_tokens=120,
            output_tokens=15,
        )

    monkeypatch.setattr(FakeLLMUnitOfWork, "invoke", invoke_with_usage)
    rollups = InMemoryMarkedRollupRepository()
    # Resolved at call time: the runner's repos are the in-memory ones
    # _run_full_pipeline patches in.
    monkeypatch.setattr(
        workflow_module,
        "get_record_workflow_step_metrics_use_case",
        lambda: RecordWorkflowStepMetrics(
            alert_repository=workflow_module.get_alert_repository(),
            step_repository=workflow_module.get_workflow_step_execution_repository(),
            rollup_repository=rollups,
            timezone_name="America/Bogota",
        ),
    )

    run = _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)

    steps = run["steps"].list_by_workflow(run["workflow_id"])
    input_tokens, output_tokens = sum_step_tokens(steps)
    assert input_tokens > 0 and output_tokens > 0
    for level in (RollupLevel.DAY, RollupLevel.MONTH, RollupLevel.YEAR):
        assert rollups.total(MetricsDataType.LLM_CALL, level, "input_tokens") == input_tokens
        assert rollups.total(MetricsDataType.LLM_CALL, level, "output_tokens") == output_tokens
        assert rollups.total(MetricsDataType.WORKFLOW_STEP, level, "count") == len(steps)
    assert len(rollups.markers) == len(steps)

    # Recording the same run again (a retry / the escalation path) adds nothing.
    before = {key: {m: list(v) for m, v in slots.items()} for key, slots in rollups.rows.items()}
    workflow_module.get_record_workflow_step_metrics_use_case().execute(
        RecordWorkflowStepMetricsInput(
            alert_id=run["alert_id"], workflow_execution_id=run["workflow_id"]
        )
    )
    assert rollups.rows == before


def test_reasoning_evaluation_dispatched_only_when_sampled(monkeypatch, evaluation_dispatches):
    monkeypatch.setattr(
        workflow_module,
        "get_operational_settings_repository",
        lambda: InMemoryOperationalSettingsRepository(
            OperationalSettings(reasoning_evaluation_sample_rate=1.0)
        ),
    )
    run = _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)
    assert evaluation_dispatches.calls == [(run["alert_id"], run["workflow_id"])]

    evaluation_dispatches.calls.clear()
    monkeypatch.setattr(
        workflow_module,
        "get_operational_settings_repository",
        lambda: InMemoryOperationalSettingsRepository(
            OperationalSettings(reasoning_evaluation_sample_rate=0.0)
        ),
    )
    _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)
    assert evaluation_dispatches.calls == []


# --- T2/T3: workflow + step spans and explicit workflow metrics -------------------


class SnapshotWritingRollupRepository:
    """MetricsRollupRepository fake for RecordAlertMetricsEvent: stores the
    guarded snapshot on the (in-memory) alert, ignores the deltas."""

    def apply(self, deltas, alert_guard) -> None:
        alerts = workflow_module.get_alert_repository()
        alert = alerts.get(alert_guard.alert_id)
        alerts.alerts[alert.id] = dataclasses.replace(alert, metrics=alert_guard.snapshot)


def _real_metrics_events(monkeypatch):
    settings = InMemoryOperationalSettingsRepository(
        OperationalSettings(
            amount_tiers=[
                AmountTier("low", "< 1M", 0, 1_000_000),
                AmountTier("high", ">= 1M", 1_000_000, None),
            ],
        )
    )
    monkeypatch.setattr(
        workflow_module,
        "get_record_alert_metrics_event_use_case",
        # Built per call so it reads the alert repo the test patched in.
        lambda: RecordAlertMetricsEvent(
            alert_repository=workflow_module.get_alert_repository(),
            rollup_repository=SnapshotWritingRollupRepository(),
            settings_repository=settings,
            schema_repository=InMemoryAlertSchemaRepository(SYNTHETIC_ALERT_SCHEMA),
            timezone_name="America/Bogota",
        ),
    )


_FORBIDDEN_VALUES = (
    SYNTHETIC_ALERT_PAYLOAD["customerId"],
    "15000000",
)


def _assert_no_customer_id_or_amount(spans) -> None:
    for span in spans:
        attribute_sets = [dict(span.attributes or {})] + [
            dict(event.attributes or {}) for event in span.events
        ]
        for attributes in attribute_sets:
            for key, value in attributes.items():
                last = key.rsplit(".", 1)[-1].lower()
                assert last not in {"customer_id", "customerid", "amount"}, (span.name, key)
                assert value != SYNTHETIC_ALERT_PAYLOAD["amount"]["baseValue"], (span.name, key)
                text = str(value).replace(".0", "").replace("_", "")
                for forbidden in _FORBIDDEN_VALUES:
                    assert forbidden not in text, (span.name, key, value)


def test_workflow_and_step_spans_carry_dimensions_never_customer_or_amount(monkeypatch):
    _real_metrics_events(monkeypatch)

    run = _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)

    spans = run["span_exporter"].get_finished_spans()
    by_name = {span.name: span for span in spans}
    workflow_span = by_name["alert_review_workflow"]
    assert workflow_span.attributes["alert_id"] == str(run["alert_id"])
    assert workflow_span.attributes["aria.channel"] == "mobileApp"
    assert workflow_span.attributes["aria.subchannel"] == "mobile"
    assert workflow_span.attributes["aria.amount_tier"] == "high"
    assert workflow_span.attributes["aria.status"] == "CLOSED"
    assert workflow_span.attributes["aria.mark"] == "pending"  # bidi
    assert workflow_span.attributes["aria.resolution_method"] == "bidi"
    assert workflow_span.attributes["aria.workflow.outcome"] == "CLOSED"

    step_spans = [s for s in spans if s.attributes.get("operation.type") == "workflow.step"]
    assert {s.attributes["aria.workflow.step"] for s in step_spans} >= {
        "pre_process", "profiling", "detector", "analyst", "executor", "post_process",
    }
    assert all(s.parent.span_id == workflow_span.context.span_id for s in step_spans)
    # Dimensions known before a step starts ride on its span too.
    assert by_name["alert_review_workflow.analyst"].attributes["aria.channel"] == "mobileApp"

    _assert_no_customer_id_or_amount(spans)


def test_workflow_duration_recorded_per_step_and_per_run(monkeypatch):
    run = _run_full_pipeline(monkeypatch, _ARIA_PLAYBOOK)

    durations = run["monitoring"].workflow_durations
    assert durations[-1][:2] == (WORKFLOW_TOTAL_STEP, "CLOSED")
    steps = [(step, outcome) for step, outcome, _ in durations[:-1]]
    assert ("pre_process", "SUCCEEDED") in steps
    assert ("post_process", "SUCCEEDED") in steps
    assert all(seconds >= 0 for _, _, seconds in durations)


def test_workflow_duration_records_failed_step_and_escalated_run(monkeypatch, in_memory_monitoring):
    monitoring, exporter = in_memory_monitoring
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(workflow_module, "get_async_operation_repository", lambda: operations)
    monkeypatch.setattr(workflow_module, "get_workflow_execution_repository", lambda: workflows)
    monkeypatch.setattr(workflow_module, "get_workflow_step_execution_repository", lambda: steps)
    monkeypatch.setattr(
        workflow_module, "get_analyst_escalation_dispatcher", RecordingAnalystEscalationDispatcher
    )
    _, _, workflow_id = _seed_pending_workflow(alerts, operations, workflows, {"alert_payload": {}})

    with pytest.raises(Exception):
        AlertReviewWorkflowRunner().run(workflow_id)

    assert [(step, outcome) for step, outcome, _ in monitoring.workflow_durations] == [
        ("pre_process", "FAILED"),
        (WORKFLOW_TOTAL_STEP, "ESCALATED"),
    ]
    workflow_span = next(
        s for s in exporter.get_finished_spans() if s.name == "alert_review_workflow"
    )
    assert workflow_span.status.status_code.name == "ERROR"


def test_skipped_run_records_its_duration_as_skipped(monkeypatch, in_memory_monitoring):
    monitoring, _ = in_memory_monitoring
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(workflow_module, "get_async_operation_repository", lambda: operations)
    monkeypatch.setattr(workflow_module, "get_workflow_execution_repository", lambda: workflows)
    monkeypatch.setattr(
        workflow_module,
        "get_operational_settings_repository",
        lambda: InMemoryOperationalSettingsRepository(OperationalSettings(agent_enabled=False)),
    )
    _, _, workflow_id = _seed_pending_workflow(
        alerts, operations, workflows, {"alert_payload": SYNTHETIC_ALERT_PAYLOAD, "origin": "simulator"}
    )

    AlertReviewWorkflowRunner().run(workflow_id)

    assert [(step, outcome) for step, outcome, _ in monitoring.workflow_durations] == [
        (WORKFLOW_TOTAL_STEP, "SKIPPED")
    ]
