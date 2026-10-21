from __future__ import annotations

from hashlib import sha256

from src.application.ports.agent_audit_port import AgentAuditEvent, AgentAuditRepository
from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
)
from src.application.ports.agent_release_port import AgentReleaseRepository
from src.application.ports.model_scoring_port import ModelScoringPort
from src.domain.agents.release import AgentReleaseStatus


class RecordAgentShadowObservation:
    """Compare a model-only candidate without changing the live decision."""

    def __init__(
        self,
        *,
        releases,
        components: AgentExperimentComponentResolver,
        scorer: ModelScoringPort,
        audit: AgentAuditRepository,
        now,
        stage_salt: str = "h12-v1",
    ):
        self._releases: AgentReleaseRepository = releases
        self._components = components
        self._scorer = scorer
        self._audit: AgentAuditRepository = audit
        self._now = now
        self._stage_salt = stage_salt

    def route_model_id(self, alert_id: str) -> str | None:
        releases = self._releases.list_releases(
            limit=20,
            statuses={
                AgentReleaseStatus.CANARY_5.value,
                AgentReleaseStatus.CANARY_25.value,
                AgentReleaseStatus.CANARY_50.value,
                AgentReleaseStatus.FULL.value,
            },
        )
        if not releases:
            return None
        release = releases[0]
        percentage = {
            AgentReleaseStatus.CANARY_5: 5,
            AgentReleaseStatus.CANARY_25: 25,
            AgentReleaseStatus.CANARY_50: 50,
            AgentReleaseStatus.FULL: 100,
        }[release.status]
        bucket = int(
            sha256(f"{self._stage_salt}:{alert_id}".encode()).hexdigest()[:8], 16
        ) % 100
        if bucket >= percentage:
            return None
        model_pin = next(
            pin
            for pin in release.candidate_component_pins
            if pin.component == "model"
        )
        return model_pin.entity_id if self._components.resolve(model_pin) else None

    def execute(
        self,
        alert_id: str,
        active_prediction: bool,
        candidate_prediction: bool | None = None,
    ) -> None:
        releases = self._releases.list_releases(
            limit=20,
            statuses={
                AgentReleaseStatus.SHADOW.value,
                AgentReleaseStatus.CANARY_5.value,
                AgentReleaseStatus.CANARY_25.value,
                AgentReleaseStatus.CANARY_50.value,
                AgentReleaseStatus.FULL.value,
            },
        )
        if not releases:
            return
        release = releases[0]
        for pin in release.candidate_component_pins:
            if self._components.resolve(pin) is None:
                raise RuntimeError("SHADOW_COMPONENT_PIN_INVALID")
        candidate_model = next(
            pin.entity_id
            for pin in release.candidate_component_pins
            if pin.component == "model"
        )
        if candidate_prediction is None:
            result = self._scorer.score_alert(alert_id, candidate_model)
            if "error" in result or not isinstance(
                result.get("predicted_positive"), bool
            ):
                raise RuntimeError("SHADOW_SCORING_FAILED")
            candidate_prediction = result["predicted_positive"]
        observation_id = sha256(
            f"{release.release_id}:{alert_id}".encode()
        ).hexdigest()
        created = self._releases.record_observation(
            release.release_id,
            observation_id,
            disagreement=candidate_prediction != active_prediction,
        )
        if created:
            self._audit.append(
                AgentAuditEvent(
                    session_id=release.session_id,
                    occurred_at=self._now(),
                    event_id=observation_id[:36],
                    category="release",
                    status=(
                        "SHADOW_OBSERVATION"
                        if release.status is AgentReleaseStatus.SHADOW
                        else "CANARY_OBSERVATION"
                    ),
                    reason_code="DECISION_AGREEMENT"
                    if candidate_prediction == active_prediction
                    else "DECISION_DISAGREEMENT",
                    actor="review_worker",
                    actor_id="celery:review_worker",
                    entity_id=release.release_id,
                    version=release.version,
                    snapshot_id=release.snapshot_id,
                    content_sha256=release.snapshot_sha256,
                    policy_version=release.rollout_policy_version,
                )
            )
