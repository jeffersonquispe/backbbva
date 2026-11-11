from __future__ import annotations

import uuid
from datetime import UTC

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
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
)
from src.application.ports.modus_operandi_port import (
    ModusOperandiPort,
    SimilarModusOperandi,
)
from src.application.ports.monitoring_port import ATTR_TOOL_NAME, MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.application.use_cases.alerts.classify_alert import (
    ClassifyAlertUseCase,
    _build_system_prompt,
)

# Default tool set (no enabled_tools filter, no watchlist configured) - see
# ClassifyAlertUseCase.__init__.
_DEFAULT_SYSTEM_PROMPT = _build_system_prompt(
    [
        "get_similar_frauds",
        "get_similar_taxonomy",
        "get_similar_modus_operandi",
        "calculator",
    ],
    None,
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


class RecordingSpan(NullSpan):
    """Records what is written to the span (tool spans must carry no content)."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write_input(self, data) -> None:
        self.writes.append("input")

    def write_result(self, data) -> None:
        self.writes.append("result")


class RecordingMonitoringPort(MonitoringPort):
    def __init__(self) -> None:
        self.started: list[tuple[str, str, dict | None, RecordingSpan]] = []

    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        span = RecordingSpan()
        self.started.append((operation_name, operation_type, metadata, span))
        return span

    def tool_spans(self):
        return [s for s in self.started if s[1] == "tool"]


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


def test_classify_alert_echoes_expected_classification_without_leaking_it_to_llm() -> (
    None
):
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


def test_classify_alert_echoes_ground_truth_tipo_when_reasoning_never_concludes() -> (
    None
):
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
    assert system_message.content == _DEFAULT_SYSTEM_PROMPT
    assert "campo ausente, nulo o sin historial comparable" in system_message.content
    assert "Una regla de velocidad acredita frecuencia, no fraude" in system_message.content
    assert "aunque el score sea alto" in system_message.content
    assert "no lo llames patrón habitual" in system_message.content
    assert "misma hora exacta se repite" in system_message.content
    assert "fecha de última modificación" in system_message.content


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
    assert system_message.content.startswith(_DEFAULT_SYSTEM_PROMPT)
    assert (
        "Presta especial atención a compras internacionales." in system_message.content
    )


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
        'Thought: done\nFinal Answer: {"is_fraud": "unknown", '
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


def test_classify_alert_calculator_tool_computes_exact_result() -> None:
    responses = [
        "Thought: need the exact ratio\n"
        "Action: calculator\n"
        "Action Input: 1500000 / 3",
        'Thought: done\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "unknown", "reasoning": "500000.0"}',
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

    output = use_case.execute(_input())

    assert output.reasoning == "500000.0"
    observation = llm_factory.created[0].received_messages[1][-1].content
    assert '"result": 500000.0' in observation


def test_classify_alert_calculator_disabled_when_not_in_enabled_tools() -> None:
    responses = [
        "Thought: need math\nAction: calculator\nAction Input: 1 + 1",
        'Thought: done\nFinal Answer: {"is_fraud": "unknown", '
        '"fraud_classification": "unknown", "reasoning": "no calculator"}',
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        enabled_tools={"get_similar_frauds"},
    )

    use_case.execute(_input())

    observation = llm_factory.created[0].received_messages[1][-1].content
    assert "Unknown tool" in observation


class InMemoryWatchlistRepository:
    """Hand-written fake - implements only what
    ClassifyAlertUseCase._check_watchlist_tool actually calls
    (WatchlistRepository is a Protocol, so structural typing is enough)."""

    def __init__(self, matches: dict[str, set[str]], names: dict[str, str]) -> None:
        # matches: watchlist_id -> set of normalized values it contains.
        self._matches = matches
        self._names = names
        self.elements_containing_calls: list[tuple[list[str], str]] = []

    def elements_containing(self, watchlist_ids: list[str], value: str) -> set[str]:
        self.elements_containing_calls.append((list(watchlist_ids), value))
        return {wid for wid in watchlist_ids if value in self._matches.get(wid, set())}

    def get(self, watchlist_id: str):
        from datetime import datetime

        from src.application.ports.watchlist_port import Watchlist, WatchlistType

        if watchlist_id not in self._names:
            return None
        now = datetime.now(UTC)
        return Watchlist(
            id=watchlist_id,
            name=self._names[watchlist_id],
            description="",
            list_type=WatchlistType.BLACKLIST,
            created_at=now,
            updated_at=now,
        )


def test_classify_alert_check_watchlist_tool_reports_matches() -> None:
    watchlists = InMemoryWatchlistRepository(
        matches={"wl-1": {"12345678"}},
        names={"wl-1": "Documentos reportados"},
    )
    responses = [
        "Thought: check the document\nAction: check_watchlist\nAction Input: -",
        'Thought: done\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "unknown", "reasoning": "listed document"}',
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        watchlist_repository=watchlists,
        watchlist_ids=["wl-1"],
        watchlist_compare_field="documento",
    )
    alert_input = _input()
    alert_input.pre_process.mandatory_fields["documento"] = "12345678"

    use_case.execute(alert_input)

    assert watchlists.elements_containing_calls == [(["wl-1"], "12345678")]
    observation = llm_factory.created[0].received_messages[1][-1].content
    assert "Documentos reportados" in observation


def test_classify_alert_without_watchlist_config_does_not_register_tool() -> None:
    responses = [
        "Thought: check the document\nAction: check_watchlist\nAction Input: -",
        'Thought: done\nFinal Answer: {"is_fraud": "unknown", '
        '"fraud_classification": "unknown", "reasoning": "no watchlist"}',
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

    observation = llm_factory.created[0].received_messages[1][-1].content
    assert "Unknown tool" in observation


def test_classify_alert_retries_on_invalid_output_label() -> None:
    responses = [
        'Thought: first guess\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "NOT_A_REAL_LABEL", "reasoning": "r1"}',
        'Thought: corrected\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "ACCOUNT_TAKEOVER", "reasoning": "r2"}',
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        output_labels=["ACCOUNT_TAKEOVER", "CARD_NOT_PRESENT"],
    )

    output = use_case.execute(_input())

    assert output.fraud_classification == "ACCOUNT_TAKEOVER"
    assert output.reasoning == "r2"
    # received_messages[1] is the message list sent on the *second*
    # invoke() call - its last entry is the correction Observation appended
    # after the first (invalid-label) Final Answer.
    correction = llm_factory.created[0].received_messages[1][-1].content
    assert "no es una etiqueta" in correction


def test_classify_alert_falls_back_to_unknown_when_labels_never_validate() -> None:
    responses = [
        'Thought: guess\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "NOT_A_REAL_LABEL", "reasoning": "r"}'
    ] * 6
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        output_labels=["ACCOUNT_TAKEOVER"],
    )

    output = use_case.execute(_input())

    assert output.is_fraud == "unknown"
    assert output.fraud_classification == "unknown"


def test_classify_alert_max_iterations_overrides_default() -> None:
    # Keeps calling a valid tool without ever emitting a Final Answer, so
    # the loop only stops when max_iterations (not the hardcoded
    # MAX_REACT_ITERATIONS=6 default) is exhausted.
    responses = [
        "Thought: keep digging\nAction: get_similar_frauds\nAction Input: q"
    ] * 2
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        max_iterations=2,
    )

    output = use_case.execute(_input())

    assert output.is_fraud == "unknown"
    # One invoke() call per iteration - exactly max_iterations of them.
    assert len(llm_factory.created[0].received_messages) == 2


class CannedResearchAgent:
    def research(self, request):
        from src.application.dtos.research_dtos import (
            ResearchFinding,
            ResearchResult,
            ResearchSource,
            ResearchStatus,
        )

        return ResearchResult(
            ResearchSource.VECTOR_STORE,
            ResearchStatus.EXECUTED,
            [
                ResearchFinding(
                    "vector_store_match", "mo-7", "vishing con nuevo beneficiario"
                )
            ],
        )


def test_classify_alert_consults_vector_store_research_and_logs_interactions() -> None:
    from src.application.dtos.research_dtos import ResearchSource
    from src.application.use_cases.research.research_tool import BoundedResearchTool

    responses = [
        "Thought: necesito patrones similares\n"
        "Action: search_vector_store\n"
        "Action Input: transferencia a beneficiario nuevo tras llamada",
        'Thought: listo\nFinal Answer: {"is_fraud": "fraud", '
        '"fraud_classification": "unknown", "reasoning": "coincide con mo-7"}',
    ]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    use_case = ClassifyAlertUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
        # Segment-driven calls always pass an explicit tool set - the
        # vector-store research tool must survive that filter.
        enabled_tools=set(),
        vector_store_research=BoundedResearchTool(
            CannedResearchAgent(), ResearchSource.VECTOR_STORE, max_interactions=2
        ),
    )

    output = use_case.execute(_input())

    system_prompt = llm_factory.created[0].received_messages[0][0].content
    assert "search_vector_store" in system_prompt
    observation = llm_factory.created[0].received_messages[1][-1].content
    assert "mo-7" in observation
    assert output.vector_store_interactions[0]["insights"] == (
        "transferencia a beneficiario nuevo tras llamada"
    )
    assert output.vector_store_interactions[0]["status"] == "executed"


def _calculator_use_case(responses: list[str], monitoring: MonitoringPort):
    return ClassifyAlertUseCase(
        llm_unit_of_work_factory=ScriptedLLMUnitOfWorkFactory(responses),
        monitoring=monitoring,
        model="fake-deployment",
        similar_fraud_case_port=RecordingSimilarFraudCasePort(),
        fraud_taxonomy_port=RecordingFraudTaxonomyPort(),
        modus_operandi_port=RecordingModusOperandiPort(),
    )


_FINAL = (
    'Thought: done\nFinal Answer: {"is_fraud": "fraud", '
    '"fraud_classification": "unknown", "reasoning": "ok"}'
)


def test_classify_alert_each_tool_call_emits_one_tool_span_without_content() -> None:
    monitoring = RecordingMonitoringPort()
    use_case = _calculator_use_case(
        [
            "Thought: a\nAction: calculator\nAction Input: 1500000 / 3",
            "Thought: b\nAction: calculator\nAction Input: 2 + 2",
            _FINAL,
        ],
        monitoring,
    )

    use_case.execute(_input())

    tool_spans = monitoring.tool_spans()
    assert [name for name, *_ in tool_spans] == ["tool.calculator", "tool.calculator"]
    assert all(meta == {ATTR_TOOL_NAME: "calculator"} for _, _, meta, _ in tool_spans)
    # Arguments and results (alert data) are never recorded on the tool span.
    assert all(span.writes == [] for *_, span in tool_spans)


def test_classify_alert_unknown_tool_does_not_emit_a_tool_span() -> None:
    monitoring = RecordingMonitoringPort()
    use_case = _calculator_use_case(
        ["Thought: a\nAction: does_not_exist\nAction Input: x", _FINAL], monitoring
    )

    output = use_case.execute(_input())

    assert output.is_fraud == "fraud"
    assert monitoring.tool_spans() == []
