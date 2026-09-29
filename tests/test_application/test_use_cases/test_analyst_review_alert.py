from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from src.application.dtos.analyst_review_alert_dtos import AnalystReviewAlertInput
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.configuration_port import ResolutionTag, ShortageBehavior
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.modus_operandi_library_port import ModusOperandiPlaybook
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityPort,
    OperationsCapacityRecord,
)
from src.application.use_cases.alerts.analyst_review_alert import (
    AnalystReviewAlertUseCase,
)
from src.application.use_cases.alerts.resolve_analyst_playbook import (
    ResolvedPlaybook,
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


class InMemoryOperationsCapacityPort(OperationsCapacityPort):
    def __init__(self, record: OperationsCapacityRecord) -> None:
        self._record = record

    def get_capacity(self) -> OperationsCapacityRecord:
        return self._record


class NullResolveAnalystPlaybookUseCase:
    """No modus operandi close to the alert has a playbook."""

    def execute(self, query, *, vector_store_instance_id):
        return None


class RecordingResolveAnalystPlaybookUseCase:
    def __init__(self, resolved: ResolvedPlaybook | None) -> None:
        self._resolved = resolved
        self.calls: list[dict] = []

    def execute(self, query, *, vector_store_instance_id):
        self.calls.append(
            {"query": query, "vector_store_instance_id": vector_store_instance_id}
        )
        return self._resolved


_PLAYBOOK = ModusOperandiPlaybook(
    strategy="Confirmar con el cliente por voicebot.",
    resolution=ShortageBehavior(
        resolution_tag=ResolutionTag.SEND_TO_VOICEBOT, resolution_method_id="rm-vb"
    ),
    if_no_voicebot=ShortageBehavior(resolution_tag=ResolutionTag.SCALE_TO_ANALYST),
    if_no_analyst=ShortageBehavior(resolution_tag=ResolutionTag.BLOCK_HARD),
)


def _resolved() -> ResolvedPlaybook:
    return ResolvedPlaybook(
        modus_operandi_id="mo-1", modus_operandi_title="Vishing", playbook=_PLAYBOOK
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


def _use_case(
    llm_factory: ScriptedLLMUnitOfWorkFactory,
    resolver,
    capacity: OperationsCapacityRecord | None = None,
    **kwargs,
) -> AnalystReviewAlertUseCase:
    return AnalystReviewAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        operations_capacity_port=InMemoryOperationsCapacityPort(
            capacity or _capacity()
        ),
        resolve_analyst_playbook=resolver,
        **kwargs,
    )


def test_analyst_review_sends_the_modus_operandi_playbook_and_capacity_to_the_llm() -> None:
    llm_factory = ScriptedLLMUnitOfWorkFactory(
        ['{"decision": "voicebot", "reasoning": "playbook prefers voicebot"}']
    )
    resolver = RecordingResolveAnalystPlaybookUseCase(_resolved())
    use_case = _use_case(llm_factory, resolver, vector_store_instance_id="vs-1")

    output = use_case.execute(_input())

    assert resolver.calls == [
        {
            "query": "ACCOUNT_TAKEOVER. matches known pattern",
            "vector_store_instance_id": "vs-1",
        }
    ]
    sent_data = llm_factory.created[0].received_messages[0][1].content
    assert '"modus_operandi": "Vishing"' in sent_data
    assert '"strategy": "Confirmar con el cliente por voicebot."' in sent_data
    assert '"if_no_voicebot": {"resolution_tag": "scale_to_analyst"' in sent_data
    assert '"operations_capacity"' in sent_data
    assert output.decision == "voicebot"
    assert output.reasoning == "playbook prefers voicebot"
    assert output.modus_operandi_id == "mo-1"
    assert output.modus_operandi_title == "Vishing"
    # Travels to the executor, which applies its fallbacks if the slot is gone.
    assert output.playbook == _PLAYBOOK
    assert output.operations_capacity["analysts"] == {
        "available": 5,
        "status": "available",
        "total": None,
    }
    assert llm_factory.operation_names == ["analyst"]


def test_analyst_review_without_playbook_escalates_without_calling_the_llm() -> None:
    llm_factory = ScriptedLLMUnitOfWorkFactory([])
    use_case = _use_case(llm_factory, NullResolveAnalystPlaybookUseCase())

    output = use_case.execute(_input())

    assert output.decision == "scale_to_analyst"
    assert output.playbook is None
    assert output.modus_operandi_id is None
    assert llm_factory.created == []
    assert output.operations_capacity["voicebot"]["available"] == 20


def test_analyst_review_handling_prompt_gets_playbook_and_resources() -> None:
    llm_factory = ScriptedLLMUnitOfWorkFactory(
        ['{"decision": "block", "reasoning": "ok"}']
    )
    use_case = _use_case(
        llm_factory,
        RecordingResolveAnalystPlaybookUseCase(_resolved()),
        handling_prompt="MO={modus_operandi} VB={voicebot_resources}",
    )

    use_case.execute(_input())

    sent = json.loads(
        llm_factory.created[0].received_messages[0][1].content.split("\n", 1)[1]
    )
    assert sent["handling_instructions"] == (
        "MO=Vishing VB={'available': 20, 'status': 'available', 'total': None}"
    )


def test_analyst_review_defaults_to_scale_to_analyst_on_malformed_output() -> None:
    llm_factory = ScriptedLLMUnitOfWorkFactory(["not-json"])
    use_case = _use_case(llm_factory, RecordingResolveAnalystPlaybookUseCase(_resolved()))

    output = use_case.execute(_input())

    assert output.decision == "scale_to_analyst"


def test_analyst_review_defaults_to_scale_to_analyst_on_invalid_decision() -> None:
    llm_factory = ScriptedLLMUnitOfWorkFactory(
        ['{"decision": "delete_everything", "reasoning": "oops"}']
    )
    use_case = _use_case(llm_factory, RecordingResolveAnalystPlaybookUseCase(_resolved()))

    output = use_case.execute(_input())

    assert output.decision == "scale_to_analyst"
