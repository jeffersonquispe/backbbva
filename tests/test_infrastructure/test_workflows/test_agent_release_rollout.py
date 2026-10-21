from __future__ import annotations

from src.domain.configurations.entities import AgentToolsConfig
from src.infrastructure.workflows.celery import review_agent_steps, task_factories


class _Scorer:
    def __init__(self, *, baseline_error: bool = False):
        self.calls = []
        self.baseline_error = baseline_error

    def score_alert(self, alert_id, model_id=None):
        self.calls.append((alert_id, model_id))
        if model_id == "baseline" and self.baseline_error:
            return {"error": "BASELINE_UNAVAILABLE"}
        return {
            "model_id": model_id or "baseline",
            "model_tag": model_id or "active",
            "predicted_positive": model_id == "candidate",
            "score": 0.9 if model_id == "candidate" else 0.1,
        }


class _Observer:
    def __init__(self, routed_model_id="candidate"):
        self.routed_model_id = routed_model_id
        self.calls = []

    def route_model_id(self, alert_id):
        return self.routed_model_id

    def execute(self, alert_id, active_prediction, candidate_prediction=None):
        self.calls.append((alert_id, active_prediction, candidate_prediction))


def test_canary_uses_candidate_for_assigned_alert_and_records_baseline_comparison(
    monkeypatch,
):
    scorer = _Scorer()
    observer = _Observer()
    monkeypatch.setattr(task_factories, "get_agent_shadow_observer", lambda: observer)
    monkeypatch.setattr(task_factories, "get_model_scoring_port", lambda: scorer)

    result = review_agent_steps._score_with_xgboost(
        {"alert_id": "alert-1"},
        AgentToolsConfig(use_xgboost_model=True, xgboost_model_id="baseline"),
    )

    assert result is not None and result.model_id == "candidate"
    assert scorer.calls == [("alert-1", "candidate"), ("alert-1", "baseline")]
    assert observer.calls == [("alert-1", False, True)]


def test_canary_falls_back_without_using_candidate_when_baseline_is_unavailable(
    monkeypatch,
):
    scorer = _Scorer(baseline_error=True)
    observer = _Observer()
    monkeypatch.setattr(task_factories, "get_agent_shadow_observer", lambda: observer)
    monkeypatch.setattr(task_factories, "get_model_scoring_port", lambda: scorer)

    result = review_agent_steps._score_with_xgboost(
        {"alert_id": "alert-2"},
        AgentToolsConfig(use_xgboost_model=True, xgboost_model_id="baseline"),
    )

    assert result is None
    assert observer.calls == []
