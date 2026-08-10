from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.dtos.analyst_review_alert_dtos import AnalystReviewAlertInput
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.fraud_playbook_port import (
    FraudPlaybookRecord,
    FraudPlaybookRepository,
)
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityPort,
    OperationsCapacityRecord,
)
from src.application.use_cases.alerts.analyst_review_alert import (
    AnalystReviewAlertUseCase,
)


class ScriptedLLMUnitOfWork(LLMUnitOfWork):
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.received_messages: list[list[LLMMessage]] = []

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        self.received_messages.append(list(messages))
        content = self._responses.pop(0)
        return LLMInvocationResult(content=content, model="fake-model")


class ScriptedLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.created: list[ScriptedLLMUnitOfWork] = []
        self.operation_names: list[str] = []

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        self.operation_names.append(operation_name)
        uow = ScriptedLLMUnitOfWork(self._responses)
        self.created.append(uow)
        return uow


class NullSpan(MonitoringSpan):
    def write_input(self, data) -> None:
        pass

    def write_result(self, data) -> None:
        pass

    def write_inner_logs(self, entries) -> None:
        pass

    def write_operation_metas(self, metadata) -> None:
        pass

    def record_dependency(self, name, kind, metadata=None) -> None:
        pass

    def finish(self, error=None) -> None:
        pass


class NullMonitoringPort(MonitoringPort):
    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        return NullSpan()


class InMemoryFraudPlaybookRepository(FraudPlaybookRepository):
    def __init__(self, records: list[FraudPlaybookRecord] | None = None) -> None:
        self._records = {record.classification: record for record in records or []}

    def create(self, playbook: FraudPlaybookRecord) -> FraudPlaybookRecord:
        self._records[playbook.classification] = playbook
        return playbook

    def get(self, classification: str) -> FraudPlaybookRecord | None:
        return self._records.get(classification)

    def update(self, classification: str, *, title=None, steps=None):
        raise NotImplementedError

    def list(self) -> list[FraudPlaybookRecord]:
        return list(self._records.values())


class InMemoryOperationsCapacityPort(OperationsCapacityPort):
    def __init__(self, record: OperationsCapacityRecord) -> None:
        self._record = record

    def get_capacity(self) -> OperationsCapacityRecord:
        return self._record


def _playbook(classification: str = "ACCOUNT_TAKEOVER") -> FraudPlaybookRecord:
    now = datetime.now(timezone.utc)
    return FraudPlaybookRecord(
        classification=classification,
        title="Account takeover response playbook",
        steps=["Verify device change.", "Block if confirmed."],
        created_at=now,
        updated_at=now,
    )


def _capacity(
    analysts: int = 5,
    voicebot: int = 20,
    bidi: int = 10,
) -> OperationsCapacityRecord:
    return OperationsCapacityRecord(
        analysts=ChannelCapacity(available=analysts, status="available"),
        voicebot=ChannelCapacity(available=voicebot, status="available"),
        bidi=ChannelCapacity(available=bidi, status="available"),
        updated_at=datetime.now(timezone.utc),
    )


def _input() -> AnalystReviewAlertInput:
    return AnalystReviewAlertInput(
        alert_id=uuid.uuid4(),
        pre_process=PreProcessAlertOutput(
            mandatory_fields={"customer_id": "cust-1"},
            optional_fields={},
            enrichment={},
            pre_process_note="note",
        ),
        profile=ProfileAlertOutput(
            user_profile="user profile",
            transaction_profile="transaction profile",
            transactional_profile="transactional profile",
        ),
        classification=ClassifyAlertOutput(
            is_fraud="fraud",
            fraud_classification="ACCOUNT_TAKEOVER",
            reasoning="matches known pattern",
            cot="Thought: ...",
        ),
    )


def test_analyst_review_uses_matching_playbook_and_returns_decision() -> None:
    responses = [
        '{"decision": "block", "reasoning": "playbook indicates confirmed fraud"}'
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    playbooks = InMemoryFraudPlaybookRepository([_playbook("ACCOUNT_TAKEOVER")])
    capacity = _capacity()
    use_case = AnalystReviewAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        fraud_playbook_port=playbooks,
        operations_capacity_port=InMemoryOperationsCapacityPort(capacity),
    )

    output = use_case.execute(_input())

    assert output.decision == "block"
    assert output.reasoning == "playbook indicates confirmed fraud"
    assert output.playbook_title == "Account takeover response playbook"
    assert output.operations_capacity["analysts"]["available"] == 5
    assert llm_factory.operation_names == ["analyst"]


def test_analyst_review_falls_back_to_unknown_playbook_when_no_match() -> None:
    responses = ['{"decision": "scale_to_analyst", "reasoning": "no playbook match"}']
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    playbooks = InMemoryFraudPlaybookRepository([_playbook("unknown")])
    use_case = AnalystReviewAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        fraud_playbook_port=playbooks,
        operations_capacity_port=InMemoryOperationsCapacityPort(_capacity()),
    )
    input_ = _input()
    input_.classification.fraud_classification = "SOME_OTHER_CLASSIFICATION"

    output = use_case.execute(input_)

    assert output.playbook_title == "Account takeover response playbook"


def test_analyst_review_defaults_to_scale_to_analyst_on_malformed_output() -> None:
    responses = ["not-json"]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = AnalystReviewAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        fraud_playbook_port=InMemoryFraudPlaybookRepository([_playbook()]),
        operations_capacity_port=InMemoryOperationsCapacityPort(_capacity()),
    )

    output = use_case.execute(_input())

    assert output.decision == "scale_to_analyst"


def test_analyst_review_defaults_to_scale_to_analyst_on_invalid_decision() -> None:
    responses = ['{"decision": "delete_everything", "reasoning": "oops"}']
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = AnalystReviewAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        fraud_playbook_port=InMemoryFraudPlaybookRepository([_playbook()]),
        operations_capacity_port=InMemoryOperationsCapacityPort(_capacity()),
    )

    output = use_case.execute(_input())

    assert output.decision == "scale_to_analyst"
