from __future__ import annotations

import uuid

from src.application.dtos.classify_alert_dtos import ClassifyAlertInput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.fraud_similarity_port import (
    SimilarFraudCase,
    SimilarFraudCasePort,
)
from src.application.ports.fraud_taxonomy_port import (
    FraudTaxonomyPort,
    SimilarFraudTaxonomy,
)
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.modus_operandi_port import (
    ModusOperandiPort,
    SimilarModusOperandi,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.use_cases.alerts.classify_alert import (
    _SYSTEM_PROMPT,
    ClassifyAlertUseCase,
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


class RecordingSimilarFraudCasePort(SimilarFraudCasePort):
    def __init__(self) -> None:
        self.queries: list[str] = []

    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudCase]:
        self.queries.append(query)
        return [
            SimilarFraudCase(
                case_id="case-1",
                summary="Similar case",
                outcome="confirmed_fraud",
                similarity_score=0.9,
            )
        ]


class RecordingFraudTaxonomyPort(FraudTaxonomyPort):
    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudTaxonomy]:
        return [
            SimilarFraudTaxonomy(
                code="ACCOUNT_TAKEOVER",
                name="Account takeover",
                description="desc",
                similarity_score=0.9,
            )
        ]


class RecordingModusOperandiPort(ModusOperandiPort):
    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarModusOperandi]:
        return [
            SimilarModusOperandi(
                pattern_id="mo-1", description="desc", similarity_score=0.9
            )
        ]


def _input(
    expected_classification: str | None = None,
    ground_truth_tipo: str | None = None,
) -> ClassifyAlertInput:
    return ClassifyAlertInput(
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
        expected_classification=expected_classification,
        ground_truth_tipo=ground_truth_tipo,
    )


def test_classify_alert_uses_tool_then_returns_final_answer() -> None:
    fraud_port = RecordingSimilarFraudCasePort()
    responses = [
        "Thought: need similar cases\n"
        "Action: get_similar_frauds\n"
        "Action Input: device change then high value transfer",
        "Thought: enough evidence\n"
        'Final Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "ACCOUNT_TAKEOVER", '
        '"reasoning": "matches known pattern"}',
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=fraud_port,
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
    )

    output = use_case.execute(_input())

    assert output.is_fraud == "fraud"
    assert output.fraud_classification == "ACCOUNT_TAKEOVER"
    assert output.reasoning == "matches known pattern"
    assert "get_similar_frauds" in output.cot
    assert "Observation:" in output.cot
    assert fraud_port.queries == ["device change then high value transfer"]
    assert llm_factory.operation_names == ["classification"]
    assert len(llm_factory.created[0].received_messages) == 2


def test_classify_alert_marks_unknown_when_no_final_answer_reached() -> None:
    responses = ["Thought: I am confused, no clear action"] * 6
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
    )

    output = use_case.execute(_input())

    assert output.is_fraud == "unknown"
    assert output.fraud_classification == "unknown"


def test_classify_alert_echoes_expected_classification_without_leaking_it_to_llm() -> None:
    # marcacion_final ground truth (see dataset_sampling.py) - carried
    # through to the output for the test-run UI to diff against, but must
    # never reach the LLM's messages, or the "test" stops testing anything.
    responses = [
        'Thought: done\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "ACCOUNT_TAKEOVER", "reasoning": "r"}'
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
    )

    output = use_case.execute(_input(expected_classification="risk"))

    assert output.expected_classification == "risk"
    sent_content = " ".join(
        m.content for m in llm_factory.created[0].received_messages[0]
    )
    assert "risk" not in sent_content


def test_classify_alert_marks_unknown_on_malformed_final_answer() -> None:
    responses = ["Thought: done\nFinal Answer: not-json"]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
    )

    output = use_case.execute(_input())

    assert output.is_fraud == "unknown"
    assert output.fraud_classification == "unknown"


def test_classify_alert_echoes_ground_truth_tipo_without_leaking_it_to_llm() -> None:
    # tipo ground truth (see dataset_sampling.py) - the real matured
    # outcome, separate from expected_classification (the analyst's call).
    # Carried through for classification_metrics.py, never sent to the LLM.
    responses = [
        'Thought: done\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "ACCOUNT_TAKEOVER", "reasoning": "r"}'
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
    )

    output = use_case.execute(_input(ground_truth_tipo="Fraude"))

    assert output.ground_truth_tipo == "Fraude"
    sent_content = " ".join(
        m.content for m in llm_factory.created[0].received_messages[0]
    )
    assert "Fraude" not in sent_content


def test_classify_alert_echoes_ground_truth_tipo_when_reasoning_never_concludes() -> None:
    responses = ["Thought: I am confused, no clear action"] * 6
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
    )

    output = use_case.execute(_input(ground_truth_tipo="NoFraude"))

    assert output.is_fraud == "unknown"
    assert output.ground_truth_tipo == "NoFraude"


def test_classify_alert_sends_base_system_prompt_verbatim_by_default() -> None:
    responses = [
        'Thought: done\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "ACCOUNT_TAKEOVER", "reasoning": "r"}'
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
    )

    use_case.execute(_input())

    system_message = llm_factory.created[0].received_messages[0][0]
    assert system_message.content == _SYSTEM_PROMPT


def test_classify_alert_appends_segment_extra_instructions() -> None:
    responses = [
        'Thought: done\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "ACCOUNT_TAKEOVER", "reasoning": "r"}'
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        extra_instructions="Presta especial atención a compras internacionales.",
    )

    use_case.execute(_input())

    system_message = llm_factory.created[0].received_messages[0][0]
    assert system_message.content.startswith(_SYSTEM_PROMPT)
    assert "Presta especial atención a compras internacionales." in system_message.content


def test_classify_alert_system_prompt_override_wins_over_extra_instructions() -> None:
    responses = [
        'Thought: done\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "ACCOUNT_TAKEOVER", "reasoning": "r"}'
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    override_prompt = "Full test-run override prompt including its own protocol."
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        system_prompt=override_prompt,
        extra_instructions="This must not appear in the sent prompt.",
    )

    use_case.execute(_input())

    system_message = llm_factory.created[0].received_messages[0][0]
    assert system_message.content == override_prompt


def test_classify_alert_enabled_tools_restricts_tool_dict() -> None:
    fraud_port = RecordingSimilarFraudCasePort()
    responses = [
        "Thought: try similar cases\n"
        "Action: get_similar_frauds\n"
        "Action Input: some query",
        "Thought: done\nFinal Answer: {\"is_fraud\": \"unknown\", "
        '"fraud_classification": "unknown", "reasoning": "no tool available"}',
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=fraud_port,
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        enabled_tools={"get_similar_taxonomy"},
    )

    use_case.execute(_input())

    assert fraud_port.queries == []
    # Second invoke() call is recorded with the Observation from the first
    # (filtered-out) tool call as its last message.
    observation = llm_factory.created[0].received_messages[1][-1].content
    assert "Unknown tool" in observation
