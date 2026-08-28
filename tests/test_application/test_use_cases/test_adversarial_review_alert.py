from __future__ import annotations

import uuid

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertInput,
)
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
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
from src.application.use_cases.alerts.adversarial_review_alert import (
    _SYSTEM_PROMPT,
    AdversarialReviewAlertUseCase,
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


def _input() -> AdversarialReviewAlertInput:
    return AdversarialReviewAlertInput(
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
            cot="Thought: ...\n\nFinal Answer: {...}",
        ),
    )


def _use_case(
    responses: list[str],
    fraud_port: SimilarFraudCasePort | None = None,
    **kwargs,
) -> tuple[AdversarialReviewAlertUseCase, ScriptedLLMUnitOfWorkFactory]:
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = AdversarialReviewAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=fraud_port or RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        **kwargs,
    )
    return use_case, llm_factory


def test_adversarial_review_uses_tool_then_certifies_classification() -> None:
    fraud_port = RecordingSimilarFraudCasePort()
    responses = [
        "Thought: let me verify against similar cases\n"
        "Action: get_similar_frauds\n"
        "Action Input: device change then high value transfer",
        "Thought: classification holds up\n"
        'Final Answer: {"has_issues": false, "feedback": "", '
        '"weak_points": [], "reasoning": "well supported"}',
    ]
    use_case, llm_factory = _use_case(responses, fraud_port)

    output = use_case.execute(_input())

    assert output.requires_classification_feedback is False
    assert output.feedback == ""
    assert output.weak_points == []
    assert "get_similar_frauds" in output.cot
    assert fraud_port.queries == ["device change then high value transfer"]
    assert llm_factory.operation_names == ["adversarial"]


def test_adversarial_review_flags_issues_for_feedback() -> None:
    responses = [
        "Thought: the taxonomy label looks wrong\n"
        'Final Answer: {"has_issues": true, '
        '"feedback": "Re-check the taxonomy label against ACCOUNT_TAKEOVER '
        'criteria", "weak_points": ["taxonomy mismatch"], '
        '"reasoning": "evidence does not support the label"}'
    ]
    use_case, _ = _use_case(responses)

    output = use_case.execute(_input())

    assert output.requires_classification_feedback is True
    assert output.feedback == (
        "Re-check the taxonomy label against ACCOUNT_TAKEOVER criteria"
    )
    assert output.weak_points == ["taxonomy mismatch"]


def test_adversarial_review_routes_back_when_no_final_answer_reached() -> None:
    responses = ["Thought: still checking, no clear action"] * 6
    use_case, _ = _use_case(responses)

    output = use_case.execute(_input())

    assert output.requires_classification_feedback is True


def test_adversarial_review_routes_back_on_malformed_final_answer() -> None:
    responses = ["Thought: done\nFinal Answer: not-json"]
    use_case, _ = _use_case(responses)

    output = use_case.execute(_input())

    assert output.requires_classification_feedback is True


def test_adversarial_review_sends_base_system_prompt_verbatim_by_default() -> None:
    responses = [
        'Thought: done\nFinal Answer: {"has_issues": false, "feedback": "", '
        '"weak_points": [], "reasoning": "r"}'
    ]
    use_case, llm_factory = _use_case(responses)

    use_case.execute(_input())

    system_message = llm_factory.created[0].received_messages[0][0]
    assert system_message.content == _SYSTEM_PROMPT


def test_adversarial_review_appends_segment_extra_instructions() -> None:
    responses = [
        'Thought: done\nFinal Answer: {"has_issues": false, "feedback": "", '
        '"weak_points": [], "reasoning": "r"}'
    ]
    use_case, llm_factory = _use_case(
        responses,
        extra_instructions="Presta especial atención a compras internacionales.",
    )

    use_case.execute(_input())

    system_message = llm_factory.created[0].received_messages[0][0]
    assert system_message.content.startswith(_SYSTEM_PROMPT)
    assert "Presta especial atención a compras internacionales." in system_message.content


def test_adversarial_review_system_prompt_override_wins_over_extra_instructions() -> None:
    responses = [
        'Thought: done\nFinal Answer: {"has_issues": false, "feedback": "", '
        '"weak_points": [], "reasoning": "r"}'
    ]
    override_prompt = "Full test-run override prompt including its own protocol."
    use_case, llm_factory = _use_case(
        responses,
        system_prompt=override_prompt,
        extra_instructions="This must not appear in the sent prompt.",
    )

    use_case.execute(_input())

    system_message = llm_factory.created[0].received_messages[0][0]
    assert system_message.content == override_prompt


def test_adversarial_review_enabled_tools_restricts_tool_dict() -> None:
    fraud_port = RecordingSimilarFraudCasePort()
    responses = [
        "Thought: try similar cases\n"
        "Action: get_similar_frauds\n"
        "Action Input: some query",
        'Thought: done\nFinal Answer: {"has_issues": false, "feedback": "", '
        '"weak_points": [], "reasoning": "no tool available"}',
    ]
    use_case, llm_factory = _use_case(
        responses,
        fraud_port=fraud_port,
        enabled_tools={"get_similar_taxonomy"},
    )

    use_case.execute(_input())

    assert fraud_port.queries == []
    observation = llm_factory.created[0].received_messages[1][-1].content
    assert "Unknown tool" in observation
