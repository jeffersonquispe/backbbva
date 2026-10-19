from __future__ import annotations

import uuid

from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertInput
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.application.use_cases.alerts.profile_alert import (
    _SYSTEM_PROMPT,
    ProfileAlertUseCase,
)


class RecordingLLMUnitOfWork(LLMUnitOfWork):
    def __init__(self, operation_name: str) -> None:
        self.operation_name = operation_name
        self.received_messages: list[LLMMessage] | None = None

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        self.received_messages = messages
        return LLMInvocationResult(
            content=f"{self.operation_name}-description", model="fake-model"
        )


class RecordingLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def __init__(self) -> None:
        self.created: list[RecordingLLMUnitOfWork] = []
        self.models: list[str] = []

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        self.models.append(model)
        uow = RecordingLLMUnitOfWork(operation_name)
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


class RecordingMonitoringPort(MonitoringPort):
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []

    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        self.started.append((operation_name, operation_type))
        return NullSpan()


def _pre_process_output() -> PreProcessAlertOutput:
    return PreProcessAlertOutput(
        mandatory_fields={"customer_id": "cust-1"},
        optional_fields={},
        enrichment={
            "customer_profile": {"segment": "retail"},
            "transaction_history": [{"amount": 10}],
            "personal_data_changes": [],
            "aric_signals": {"is_rat": True},
        },
        pre_process_note="note",
    )


def test_profile_alert_runs_three_inferences_and_returns_descriptions() -> None:
    llm_factory = RecordingLLMUnitOfWorkFactory()
    monitoring = RecordingMonitoringPort()
    use_case = ProfileAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=monitoring,
        model="fake-deployment",
    )

    output = use_case.execute(
        ProfileAlertInput(
            alert_id=uuid.uuid4(),
            pre_process=_pre_process_output(),
        )
    )

    assert output.user_profile == "user_profile-description"
    assert output.transaction_profile == "transaction_profile-description"
    assert output.transactional_profile == "transactional_profile-description"
    assert [uow.operation_name for uow in llm_factory.created] == [
        "user_profile",
        "transaction_profile",
        "transactional_profile",
    ]
    assert llm_factory.models == ["fake-deployment"] * 3
    for uow in llm_factory.created:
        assert uow.received_messages is not None
        assert len(uow.received_messages) == 2


def test_profile_alert_default_system_prompt_used_for_all_three_operations() -> None:
    llm_factory = RecordingLLMUnitOfWorkFactory()
    use_case = ProfileAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=RecordingMonitoringPort(),
        model="fake-deployment",
    )

    use_case.execute(
        ProfileAlertInput(alert_id=uuid.uuid4(), pre_process=_pre_process_output())
    )

    for uow in llm_factory.created:
        assert uow.received_messages[0].content == _SYSTEM_PROMPT


def test_profile_alert_extra_instructions_applies_only_to_its_own_operation() -> None:
    llm_factory = RecordingLLMUnitOfWorkFactory()
    use_case = ProfileAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=RecordingMonitoringPort(),
        model="fake-deployment",
        extra_instructions={"transaction_profile": "Foo"},
    )

    use_case.execute(
        ProfileAlertInput(alert_id=uuid.uuid4(), pre_process=_pre_process_output())
    )

    user_profile, transaction_profile, transactional_profile = llm_factory.created
    assert user_profile.received_messages[0].content == _SYSTEM_PROMPT
    assert transactional_profile.received_messages[0].content == _SYSTEM_PROMPT
    transaction_content = transaction_profile.received_messages[0].content
    assert transaction_content.startswith(_SYSTEM_PROMPT)
    assert "Foo" in transaction_content


def test_profile_alert_system_prompt_override_wins_over_extra_instructions() -> None:
    llm_factory = RecordingLLMUnitOfWorkFactory()
    override_prompt = "Full test-run override prompt."
    use_case = ProfileAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=RecordingMonitoringPort(),
        model="fake-deployment",
        system_prompt=override_prompt,
        extra_instructions={"user_profile": "must not appear"},
    )

    use_case.execute(
        ProfileAlertInput(alert_id=uuid.uuid4(), pre_process=_pre_process_output())
    )

    for uow in llm_factory.created:
        assert uow.received_messages[0].content == override_prompt
