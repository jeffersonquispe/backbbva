from __future__ import annotations

from datetime import UTC, datetime

from src.application.use_cases.agent.record_agent_shadow_observation import (
    RecordAgentShadowObservation,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.release import AgentRelease, AgentReleaseStatus


def _pin(component: str, version: str) -> ComponentVersionReference:
    return ComponentVersionReference.pin(
        component, f"{component}-{version}", version, {"version": version}
    )


class _ReleaseRepository:
    def __init__(self, status):
        now = datetime(2026, 10, 21, tzinfo=UTC)
        self.release = AgentRelease(
            release_id="release-1",
            validation_id="validation-1",
            session_id="session-1",
            experiment_id="experiment-1",
            status=status,
            candidate_component_pins=tuple(
                _pin(component, "candidate")
                for component in ("model", "configuration", "library", "vector_store")
            ),
            previous_component_pins=tuple(
                _pin(component, "baseline")
                for component in ("model", "configuration", "library", "vector_store")
            ),
            requested_by="requester",
            requested_by_id="channel-manager",
            requested_at=now,
            title="test",
            reason="test reason",
        )
        self.recorded = []

    def list_releases(self, limit=100, statuses=None):
        return [self.release] if statuses and self.release.status.value in statuses else []

    def record_observation(self, release_id, observation_id, *, disagreement):
        self.recorded.append((release_id, observation_id, disagreement))
        return True


class _Components:
    def resolve(self, reference):
        return object()


class _Scorer:
    def __init__(self, prediction=True):
        self.calls = []
        self.prediction = prediction

    def score_alert(self, alert_id, model_id=None):
        self.calls.append((alert_id, model_id))
        return {"predicted_positive": self.prediction}


class _Audit:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


def test_canary_routes_stably_and_records_candidate_comparison():
    releases = _ReleaseRepository(AgentReleaseStatus.CANARY_5)
    scorer = _Scorer()
    audit = _Audit()
    observer = RecordAgentShadowObservation(
        releases=releases,
        components=_Components(),
        scorer=scorer,
        audit=audit,
        now=lambda: datetime(2026, 10, 21, tzinfo=UTC),
    )
    selected = next(
        alert_id
        for alert_id in (f"alert-{index}" for index in range(100))
        if observer.route_model_id(alert_id) == "model-candidate"
    )

    assert observer.route_model_id(selected) == observer.route_model_id(selected)
    observer.execute(selected, active_prediction=False, candidate_prediction=True)

    assert len(releases.recorded) == 1
    assert releases.recorded[0][2] is True
    assert scorer.calls == []
    assert audit.events[0].status == "CANARY_OBSERVATION"
    assert audit.events[0].actor_id == "celery:review_worker"
    assert audit.events[0].entity_id == "release-1"
