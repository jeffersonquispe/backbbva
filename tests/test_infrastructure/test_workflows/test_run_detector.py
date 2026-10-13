from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import src.infrastructure.workflows.celery.alert_review_workflow as workflow_module
import src.infrastructure.workflows.celery.history_research as history_research_module
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.profile_alert_dtos import ProfileAlertOutput
from src.application.ports.configuration_port import (
    AgentSettings,
    ConfigurationRecord,
    DelegatedResearchSettings,
    DetectorConfig,
    GeneralSettings,
    HistoryPandasResearchConfig,
    InfraSettings,
    Rubric,
    RuleCondition,
    SegmentSettings,
    TestSettings,
)
from src.application.ports.host_service_transaction_history_port import (
    TransactionHistoryEntry,
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


def _context(segment: SegmentSettings) -> dict[str, Any]:
    return {
        "alert_id": "00000000-0000-0000-0000-000000000001",
        "active_configuration": _config_with_segment(segment),
        "segment_code": "tarjetas",
        "input": {"alert_payload": {"amount": 5000}},
        "pre_process": PreProcessAlertOutput(
            mandatory_fields={
                "customer_id": "cust-1",
                "event_time": "2026-09-28T00:00:00Z",
            },
            optional_fields={"amount": 5000, "device": "android"},
            enrichment={
                "aric_signals": None,
                "customer_profile": None,
                "transaction_history": [
                    TransactionHistoryEntry(
                        "e-old", "transfer", "2026-06-01T00:00:00Z", 1.0
                    ),
                    TransactionHistoryEntry(
                        "e-new", "transfer", "2026-09-27T00:00:00Z", 2.0
                    ),
                ],
                "personal_data_changes": [],
            },
            pre_process_note="",
        ),
        "profiling": ProfileAlertOutput(
            user_profile="", transaction_profile="", transactional_profile=""
        ),
    }


class RecordingClassifyAlertUseCase:
    def __init__(self, inputs: list[Any], is_fraud: str = "fraud") -> None:
        self._inputs = inputs
        self._is_fraud = is_fraud

    def execute(self, input):
        self._inputs.append(input)
        return ClassifyAlertOutput(
            is_fraud=self._is_fraud, fraud_classification="unknown", reasoning="llm"
        )


def _patched(monkeypatch, is_fraud: str = "fraud") -> tuple[list[dict], list[Any]]:
    calls: list[dict[str, Any]] = []
    inputs: list[Any] = []

    def fake_get_classify_alert_use_case(**kwargs):
        calls.append(kwargs)
        return RecordingClassifyAlertUseCase(inputs, is_fraud)

    monkeypatch.setattr(
        workflow_module, "get_classify_alert_use_case", fake_get_classify_alert_use_case
    )
    return calls, inputs


def _rubric() -> Rubric:
    return Rubric(
        id="r1",
        name="estafa_score",
        conditions=[
            RuleCondition(
                id="c1", variable="amount", comparison="gt", values=["3000"], score=60
            ),
            RuleCondition(
                id="c2", variable="device", comparison="eq", values=["iphone"], score=40
            ),
        ],
    )


# ── Rúbricas (#1/#2) ─────────────────────────────────────────


def test_rubrics_score_additively_per_matched_condition() -> None:
    segment = SegmentSettings(enabled=True, agent=AgentSettings(rubrics=[_rubric()]))

    result = workflow_module._run_rubrics(_context(segment))

    # amount > 3000 matches, device == iphone doesn't - partial credit, not
    # the old all-conditions-or-nothing gate.
    assert result == {
        "scores": [
            {
                "id": "r1",
                "name": "estafa_score",
                "score": 60,
                "max_score": 100,
                "matched_condition_ids": ["c1"],
            }
        ],
        "evaluated": 1,
    }


def test_detector_prompt_receives_rubric_scores(monkeypatch) -> None:
    calls, _ = _patched(monkeypatch)
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            rubrics=[_rubric()], detector=DetectorConfig(prompt="Evalúa")
        ),
    )
    context = _context(segment)
    context["rubrics"] = workflow_module._run_rubrics(context)

    workflow_module._run_detector(context)

    assert calls[0]["extra_instructions"].startswith("Evalúa")
    assert "estafa_score: 60/100" in calls[0]["extra_instructions"]


# ── XGBoost (#3) ─────────────────────────────────────────


def _xgboost_score(is_fraud: str) -> workflow_module._XGBoostScore:
    return workflow_module._XGBoostScore(
        score=0.9 if is_fraud == "fraud" else 0.5,
        model_id="model-1",
        model_tag="v1",
        is_fraud=is_fraud,
        verdict="superó el umbral de fraude" if is_fraud == "fraud" else "banda",
        fraud_threshold=0.8,
        uncertainty_threshold=0.4,
        top_features=[{"feature": "amount", "contribution": 0.3, "value": "5000"}],
    )


def _xgboost_segment() -> SegmentSettings:
    return SegmentSettings(
        enabled=True,
        agent=AgentSettings(detector=DetectorConfig(use_xgboost_model=True)),
    )


def test_xgboost_decisive_score_skips_the_llm(monkeypatch) -> None:
    calls, _ = _patched(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "_score_with_xgboost",
        lambda context, cfg: _xgboost_score("fraud"),
    )

    output = workflow_module._run_detector(_context(_xgboost_segment()))

    assert calls == []
    assert output.is_fraud == "fraud"
    assert output.model_output["score"] == 0.9
    assert output.model_output["top_features"][0]["feature"] == "amount"


def test_xgboost_uncertainty_band_lets_the_llm_decide_with_separate_evidence(
    monkeypatch,
) -> None:
    calls, _ = _patched(monkeypatch, is_fraud="not_fraud")
    monkeypatch.setattr(
        workflow_module,
        "_score_with_xgboost",
        lambda context, cfg: _xgboost_score("unknown"),
    )

    output = workflow_module._run_detector(_context(_xgboost_segment()))

    assert len(calls) == 1
    assert "Salida del modelo XGBoost" in calls[0]["extra_instructions"]
    assert '"top_features"' in calls[0]["extra_instructions"]
    # LLM's verdict stands; the model output is kept apart from it.
    assert output.is_fraud == "not_fraud"
    assert output.reasoning == "llm"
    assert output.model_output["prediction"] == "unknown"


@dataclass
class _Model:
    id: Any
    tag: str
    storage_ref: str | None


class InMemoryModelRepository:
    def __init__(self, model: _Model | None) -> None:
        self._model = model

    def get(self, model_id):
        return self._model if self._model and self._model.id == model_id else None

    def get_active(self):
        return self._model


def test_xgboost_falls_back_to_llm_when_model_is_not_trained(monkeypatch) -> None:
    calls, _ = _patched(monkeypatch)
    model_id = uuid4()
    monkeypatch.setattr(
        workflow_module,
        "get_model_repository",
        lambda: InMemoryModelRepository(_Model(model_id, "v1", storage_ref=None)),
    )
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            detector=DetectorConfig(
                use_xgboost_model=True, xgboost_model_id=str(model_id)
            )
        ),
    )

    output = workflow_module._run_detector(_context(segment))

    assert len(calls) == 1
    assert output.is_fraud == "fraud"
    assert output.model_output is None


# ── Análisis de historial + selector (#4) ──────────────────────


def _history_cfg(**overrides) -> DetectorConfig:
    return DetectorConfig(
        delegated_research=DelegatedResearchSettings(
            history_pandas=HistoryPandasResearchConfig(enabled=True, **overrides)
        )
    )


def test_history_analysis_analyzes_only_the_selected_slice() -> None:
    segment = SegmentSettings(enabled=True, agent=AgentSettings())
    cfg = _history_cfg(window_days=30, max_history_rows=10, allowed_columns=["amount"])

    [result] = history_research_module._history_research(
        _context(segment), cfg, "inconclusa"
    )

    assert result["status"] == "executed"
    # e-old (June) falls outside the 30-day window before the alert.
    assert result["trace"][0] == {"rows_considered": 1}


def test_history_analysis_disabled_does_nothing() -> None:
    segment = SegmentSettings(enabled=True, agent=AgentSettings())

    assert (
        history_research_module._history_research(
            _context(segment), DetectorConfig(), "x"
        )
        == []
    )


def test_inconclusive_detector_reruns_with_history_findings(monkeypatch) -> None:
    calls, _ = _patched(monkeypatch, is_fraud="unknown")
    monkeypatch.setattr(
        history_research_module,
        "_history_research",
        lambda context, cfg, reasoning: [{"source": "history_pandas"}],
    )
    segment = SegmentSettings(
        enabled=True, agent=AgentSettings(detector=_history_cfg())
    )

    output = workflow_module._run_detector(_context(segment))

    assert len(calls) == 2
    assert "análisis de historial" in calls[1]["extra_instructions"]
    assert output.research_delegations == [{"source": "history_pandas"}]


def _numbered_history_research(monkeypatch) -> list[str]:
    reasonings: list[str] = []

    def fake(context, cfg, reasoning):
        reasonings.append(reasoning)
        return [{"status": "executed", "findings": [{"round": len(reasonings)}]}]

    monkeypatch.setattr(history_research_module, "_history_research", fake)
    return reasonings


def test_history_runs_up_to_max_delegations_rounds_while_inconclusive(
    monkeypatch,
) -> None:
    calls, _ = _patched(monkeypatch, is_fraud="unknown")
    rounds = _numbered_history_research(monkeypatch)
    segment = SegmentSettings(
        enabled=True, agent=AgentSettings(detector=_history_cfg(max_delegations=3))
    )

    output = workflow_module._run_detector(_context(segment))

    assert len(rounds) == 3
    assert len(calls) == 4  # first answer + one re-run per round
    assert [item["findings"] for item in output.research_delegations] == [
        [{"round": 1}],
        [{"round": 2}],
        [{"round": 3}],
    ]


def test_history_rounds_are_capped_at_five(monkeypatch) -> None:
    _patched(monkeypatch, is_fraud="unknown")
    rounds = _numbered_history_research(monkeypatch)
    segment = SegmentSettings(
        enabled=True, agent=AgentSettings(detector=_history_cfg(max_delegations=50))
    )

    workflow_module._run_detector(_context(segment))

    assert len(rounds) == 5


def test_history_rounds_stop_once_the_step_concludes(monkeypatch) -> None:
    calls, _ = _patched(monkeypatch, is_fraud="fraud")
    rounds = _numbered_history_research(monkeypatch)
    segment = SegmentSettings(
        enabled=True, agent=AgentSettings(detector=_history_cfg(max_delegations=5))
    )

    output = workflow_module._run_detector(_context(segment))

    assert rounds == []
    assert len(calls) == 1
    assert output.research_delegations is None


def test_history_rounds_stop_when_a_round_repeats_the_same_findings(
    monkeypatch,
) -> None:
    calls, _ = _patched(monkeypatch, is_fraud="unknown")
    monkeypatch.setattr(
        history_research_module,
        "_history_research",
        lambda context, cfg, reasoning: [
            {"status": "executed", "findings": [{"same": 1}]}
        ],
    )
    segment = SegmentSettings(
        enabled=True, agent=AgentSettings(detector=_history_cfg(max_delegations=5))
    )

    output = workflow_module._run_detector(_context(segment))

    assert len(calls) == 2
    assert len(output.research_delegations) == 1
