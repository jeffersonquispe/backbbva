from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import src.infrastructure.workflows.celery.review_action_steps as workflow_module
from src.application.dtos.analyst_review_alert_dtos import AnalystReviewAlertOutput
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.generate_agent_text_dtos import GenerateAgentTextOutput
from src.application.dtos.post_process_alert_dtos import PostProcessAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.ports.alert_action_dispatcher_port import AlertActionDispatchRef
from src.application.ports.analyst_escalation_port import AnalystEscalationRef
from src.application.ports.configuration_port import (
    AgentSettings,
    ConfigurationRecord,
    DocumentationConfig,
    DocumentationStrategy,
    ExecutorConfig,
    GeneralSettings,
    InfraSettings,
    PromptField,
    SegmentSettings,
    TestSettings,
    VoicebotCategoryPrompt,
    VoicebotConfig,
)
from src.application.use_cases.alerts.route_alert_resolution import (
    FallbackStep,
    ResolutionRouting,
)


def _config_with_segment(segment: SegmentSettings) -> ConfigurationRecord:
    now = datetime.now(UTC)
    return ConfigurationRecord(
        configuration_id="cfg-1",
        version=1,
        name="cfg-1-v1",
        description="",
        active=True,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=TestSettings(),
        created_at=now,
        updated_at=now,
        segments={"tarjetas": segment},
    )


def _context(
    segment: SegmentSettings | None, decision: str, **extra: Any
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "alert_id": str(uuid4()),
        "workflow_execution_id": str(uuid4()),
        "workflow_started_at": datetime.now(UTC).isoformat(),
        "input": {},
        "pre_process": PreProcessAlertOutput(
            mandatory_fields={"customer_id": "cust-1"},
            optional_fields={"amount": 1200.5},
            enrichment={
                "aric_signals": None,
                "customer_profile": None,
                "transaction_history": [],
                "personal_data_changes": [],
            },
            pre_process_note="",
        ),
        "classification": ClassifyAlertOutput(
            is_fraud="fraud", fraud_classification="ACCOUNT_TAKEOVER", reasoning="r"
        ),
        "analyst": AnalystReviewAlertOutput(
            decision=decision, reasoning="analyst reasoning"
        ),
    }
    if segment is not None:
        base["active_configuration"] = _config_with_segment(segment)
        base["segment_code"] = "tarjetas"
    base.update(extra)
    return base


class RecordingAlertActionDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, str | None]] = []

    def dispatch(self, action, alert_id, content=None):
        self.calls.append((action, alert_id, content))
        return AlertActionDispatchRef(backend="celery", external_id="ref-1")


class RecordingAnalystEscalationDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, alert_id, workflow_execution_id, event_id, session_id, reason):
        self.calls.append({"reason": reason})
        return AnalystEscalationRef(backend="celery", external_id="ref-2")


class RecordingGenerateAgentTextUseCase:
    def __init__(self, text: str) -> None:
        self._text = text
        self.received_prompts: list[str] = []

    def execute(self, input):
        self.received_prompts.append(input.prompt)
        return GenerateAgentTextOutput(text=self._text)


class ScriptedRouteAlertResolutionUseCase:
    """Returns a fixed routing, or passes the analyst's decision through
    unchanged (resources available) when none is scripted."""

    def __init__(self, routing: ResolutionRouting | None = None) -> None:
        self._routing = routing
        self.calls: list[dict[str, Any]] = []

    def execute(self, *, alert_id, decision, playbook):
        self.calls.append({"decision": decision, "playbook": playbook})
        return self._routing or ResolutionRouting(decision=decision)


def _patch_dispatchers(monkeypatch, routing: ResolutionRouting | None = None):
    router = ScriptedRouteAlertResolutionUseCase(routing)
    monkeypatch.setattr(
        workflow_module, "get_route_alert_resolution_use_case", lambda: router
    )
    action_dispatcher = RecordingAlertActionDispatcher()
    escalation_dispatcher = RecordingAnalystEscalationDispatcher()
    monkeypatch.setattr(
        workflow_module, "get_alert_action_dispatcher", lambda: action_dispatcher
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_escalation_dispatcher",
        lambda: escalation_dispatcher,
    )
    monkeypatch.setattr(
        workflow_module, "get_alert_repository", lambda: _NullAlertRepository()
    )
    return action_dispatcher, escalation_dispatcher


class _NullAlertRepository:
    def get(self, alert_id):
        return None


def _executor_segment(**executor_kwargs) -> SegmentSettings:
    return SegmentSettings(
        enabled=True,
        agent=AgentSettings(executor=ExecutorConfig(**executor_kwargs)),
    )


def test_run_executor_generates_aric_marking_comment_for_block(monkeypatch) -> None:
    action_dispatcher, _ = _patch_dispatchers(monkeypatch)
    recorder = RecordingGenerateAgentTextUseCase("Comentario generado")
    monkeypatch.setattr(
        workflow_module,
        "get_generate_agent_text_use_case",
        lambda **kwargs: recorder,
    )
    segment = _executor_segment(
        aric_marking=PromptField(prompt="Marca a {customer_id} por {amount}")
    )

    workflow_module._run_executor(_context(segment, "block"))

    assert recorder.received_prompts == ["Marca a cust-1 por 1200.5"]
    action, alert_id, content = action_dispatcher.calls[0]
    assert action == "block"
    assert content == "Comentario generado"


def test_run_executor_skips_generation_when_aric_marking_prompt_empty(
    monkeypatch,
) -> None:
    action_dispatcher, _ = _patch_dispatchers(monkeypatch)
    segment = _executor_segment()  # aric_marking.prompt == ""

    workflow_module._run_executor(_context(segment, "block"))

    assert action_dispatcher.calls[0] == ("block", action_dispatcher.calls[0][1], None)


def test_run_executor_builds_voicebot_script_from_base_and_category_prompt(
    monkeypatch,
) -> None:
    action_dispatcher, _ = _patch_dispatchers(monkeypatch)
    segment = _executor_segment(
        voicebot_call=VoicebotConfig(
            base_prompt="Hola {customer_id}",
            category_prompts=[
                VoicebotCategoryPrompt(
                    id="vcp-1",
                    taxonomy_id="ACCOUNT_TAKEOVER",
                    prompt="Pregunta sobre {amount}",
                ),
                VoicebotCategoryPrompt(
                    id="vcp-2", taxonomy_id="OTHER", prompt="No debería aparecer"
                ),
            ],
        )
    )

    workflow_module._run_executor(_context(segment, "voicebot"))

    _, _, content = action_dispatcher.calls[0]
    assert content == "Hola cust-1\n\nPregunta sobre 1200.5"


def test_run_executor_renders_escalation_prompt_with_variables(monkeypatch) -> None:
    _, escalation_dispatcher = _patch_dispatchers(monkeypatch)
    segment = _executor_segment(
        analyst_escalation=PromptField(prompt="Revisar a {customer_id}, monto {amount}")
    )

    workflow_module._run_executor(_context(segment, "scale_to_analyst"))

    assert escalation_dispatcher.calls == [{"reason": "Revisar a cust-1, monto 1200.5"}]


def test_run_executor_falls_back_to_analyst_reasoning_when_no_escalation_prompt(
    monkeypatch,
) -> None:
    _, escalation_dispatcher = _patch_dispatchers(monkeypatch)
    segment = _executor_segment()  # analyst_escalation.prompt == ""

    workflow_module._run_executor(_context(segment, "scale_to_analyst"))

    assert escalation_dispatcher.calls == [{"reason": "analyst reasoning"}]


def test_run_executor_follows_the_routed_fallback_and_records_it(monkeypatch) -> None:
    # The analyst chose voicebot, but no slot was left: the playbook's
    # fallback (a hard block) is what actually runs.
    routing = ResolutionRouting(
        decision="block",
        block_mode="hard",
        fallbacks=[
            FallbackStep(
                from_decision="voicebot",
                reason="voicebot_unavailable",
                to_decision="block",
                resolution_method_id="rm-hard",
            )
        ],
    )
    action_dispatcher, _ = _patch_dispatchers(monkeypatch, routing)

    output = workflow_module._run_executor(_context(None, "voicebot"))

    assert action_dispatcher.calls[0][0] == "block"
    assert output["executed_action"] == "block"
    assert output["decided_action"] == "voicebot"
    assert output["block_mode"] == "hard"
    assert output["fallbacks"] == [
        {
            "from_decision": "voicebot",
            "reason": "voicebot_unavailable",
            "to_decision": "block",
            "resolution_method_id": "rm-hard",
        }
    ]


def test_run_executor_records_the_voicebot_reservation(monkeypatch) -> None:
    _patch_dispatchers(
        monkeypatch, ResolutionRouting(decision="voicebot", reservation_id="res-1")
    )

    output = workflow_module._run_executor(_context(None, "voicebot"))

    assert output["executed_action"] == "voicebot"
    assert output["voicebot_reservation_id"] == "res-1"
    assert "fallbacks" not in output


def test_run_executor_without_active_segment_does_not_generate_content(
    monkeypatch,
) -> None:
    action_dispatcher, _ = _patch_dispatchers(monkeypatch)

    workflow_module._run_executor(_context(None, "block"))

    assert action_dispatcher.calls[0][2] is None


def test_run_post_process_renders_template_documentation(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_module,
        "get_post_process_alert_use_case",
        lambda: _EchoingPostProcessAlertUseCase(),
    )
    segment = _executor_segment(
        documentador=DocumentationConfig(
            strategy=DocumentationStrategy.TEMPLATE,
            template="Cliente {customer_id} - monto {amount}",
        )
    )

    output = workflow_module._run_post_process(_context(segment, "block"))

    assert output.documentation == "Cliente cust-1 - monto 1200.5"


def test_run_post_process_generates_agent_documentation(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_module,
        "get_post_process_alert_use_case",
        lambda: _EchoingPostProcessAlertUseCase(),
    )
    recorder = RecordingGenerateAgentTextUseCase("Documento redactado por el agente")
    monkeypatch.setattr(
        workflow_module,
        "get_generate_agent_text_use_case",
        lambda **kwargs: recorder,
    )
    segment = _executor_segment(
        documentador=DocumentationConfig(
            strategy=DocumentationStrategy.AGENT,
            agent_prompt="Documenta el caso de {customer_id}",
        )
    )

    output = workflow_module._run_post_process(_context(segment, "block"))

    assert recorder.received_prompts == ["Documenta el caso de cust-1"]
    assert output.documentation == "Documento redactado por el agente"


def test_run_post_process_without_active_segment_has_no_documentation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workflow_module,
        "get_post_process_alert_use_case",
        lambda: _EchoingPostProcessAlertUseCase(),
    )

    output = workflow_module._run_post_process(_context(None, "block"))

    assert output.documentation == ""


class _EchoingPostProcessAlertUseCase:
    """Stands in for the real PostProcessAlertUseCase (a pure "package the
    input into the output" step - see post_process_alert.py) so this test
    only exercises _run_post_process's documentation-building logic."""

    def execute(self, input):
        return PostProcessAlertOutput(
            status="success",
            resolution_path=input.resolution_path,
            total_duration_seconds=0.0,
            closed_at=datetime.now(UTC).isoformat(),
            documentation=input.documentation,
        )
