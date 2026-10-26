from __future__ import annotations

from dataclasses import replace

from src.application.ports.agent_audit_port import AgentAuditEvent, AgentAuditRepository
from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
)
from src.application.ports.agent_release_port import AgentReleaseRepository
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.domain.agents.event import AgentEventKind, AgentEventOutcome
from src.domain.agents.release import (
    AgentRelease,
    AgentReleaseStatus,
    RetrospectiveValidationStatus,
)


class AgentReleasePolicyError(ValueError):
    pass


_MINIMUM_STAGE_OBSERVATIONS = 30
_MAXIMUM_DECISION_DISAGREEMENT_PCT = 5
_ROLLOUT_POLICY_VERSION = "h12_model_only_v1"
# Release steps that change what production runs. They are written to the
# global audit log as well as to the session timeline.
_PRODUCTION_STATUSES = {
    "RELEASE_APPROVED": "Release aprobado",
    "ROLLOUT_ADVANCED": "Despliegue gradual avanzado",
    "ROLLED_BACK": "Release revertido",
}


class ManageAgentReleaseUseCase:
    def __init__(
        self,
        *,
        releases: AgentReleaseRepository,
        components: AgentExperimentComponentResolver,
        audit: AgentAuditRepository,
        now,
        new_id,
        timeline: AgentTimeline | None = None,
    ) -> None:
        self._releases = releases
        self._components = components
        self._audit = audit
        self._timeline = timeline
        self._now = now
        self._new_id = new_id

    def request(
        self,
        *,
        validation_id: str,
        title: str,
        reason: str,
        actor: str,
        actor_id: str,
    ) -> AgentRelease:
        validation = self._releases.get_validation(validation_id)
        if validation is None:
            raise AgentReleasePolicyError("VALIDATION_NOT_FOUND")
        if validation.status is not RetrospectiveValidationStatus.PASSED:
            raise AgentReleasePolicyError("VALIDATION_FAILED")
        baseline = {pin.component: pin for pin in validation.baseline_component_pins}
        candidate = {pin.component: pin for pin in validation.component_pins}
        if any(
            baseline.get(component) != candidate.get(component)
            for component in {"configuration", "library", "vector_store"}
        ):
            raise AgentReleasePolicyError("UNSUPPORTED_COMPONENT_ROLLOUT")
        try:
            current_stack = self._components.active_baseline()
        except ValueError as error:
            raise AgentReleasePolicyError("ACTIVE_STACK_CHANGED") from error
        if not _same_pins(current_stack, validation.baseline_component_pins):
            raise AgentReleasePolicyError("ACTIVE_STACK_CHANGED")
        if self._releases.list_releases(
            limit=20,
            statuses={
                AgentReleaseStatus.SHADOW.value,
                AgentReleaseStatus.PENDING_APPROVAL.value,
                AgentReleaseStatus.CANARY_5.value,
                AgentReleaseStatus.CANARY_25.value,
                AgentReleaseStatus.CANARY_50.value,
                AgentReleaseStatus.FULL.value,
            },
        ):
            raise AgentReleasePolicyError("ACTIVE_RELEASE_EXISTS")
        now = self._now()
        release = AgentRelease(
            release_id=self._new_id(),
            validation_id=validation.validation_id,
            session_id=validation.session_id,
            experiment_id=validation.experiment_id,
            status=AgentReleaseStatus.SHADOW,
            candidate_component_pins=validation.component_pins,
            previous_component_pins=validation.baseline_component_pins,
            requested_by=actor,
            requested_by_id=actor_id,
            requested_at=now,
            title=title.strip(),
            reason=reason.strip(),
            snapshot_id=validation.snapshot_id,
            snapshot_sha256=validation.snapshot_sha256,
            rollout_policy_version=_ROLLOUT_POLICY_VERSION,
            updated_at=now,
        )
        try:
            result = self._releases.create_release(release)
        except ValueError as error:
            raise AgentReleasePolicyError(str(error)) from error
        self._audit_event(release, "RELEASE_REQUESTED", actor=actor, actor_id=actor_id)
        self._audit_event(release, "SHADOW_STARTED", actor=actor, actor_id=actor_id)
        return result

    def submit_for_approval(
        self,
        release_id: str,
        *,
        expected_version: int,
        actor: str,
        actor_id: str,
        reason: str,
    ) -> AgentRelease:
        release = self._get(release_id)
        if release.status is not AgentReleaseStatus.SHADOW:
            raise AgentReleasePolicyError("INVALID_STATE")
        _validate_observation_guardrail(release.observations)
        updated = replace(
            release,
            status=AgentReleaseStatus.PENDING_APPROVAL,
            version=expected_version + 1,
            updated_at=self._now(),
        )
        result = self._releases.update_release(
            updated, expected_version=expected_version
        )
        self._audit_event(
            result,
            "SHADOW_COMPLETED",
            reason=reason,
            actor=actor,
            actor_id=actor_id,
        )
        return result

    def approve(
        self,
        release_id: str,
        *,
        expected_version: int,
        actor: str,
        actor_id: str,
        reason: str,
    ) -> AgentRelease:
        release = self._get(release_id)
        self._assert_previous_stack(release)
        if release.status is not AgentReleaseStatus.PENDING_APPROVAL:
            raise AgentReleasePolicyError("INVALID_STATE")
        if release.requested_by_id == actor_id:
            raise AgentReleasePolicyError("SELF_APPROVAL")
        updated = replace(
            release,
            status=AgentReleaseStatus.CANARY_5,
            approved_by=actor,
            approved_by_id=actor_id,
            approved_at=self._now(),
            updated_at=self._now(),
            version=expected_version + 1,
            observations={},
        )
        result = self._releases.update_release(
            updated, expected_version=expected_version
        )
        self._audit_event(
            result, "RELEASE_APPROVED", reason=reason, actor=actor, actor_id=actor_id
        )
        self._audit_event(
            result,
            "ROLLOUT_ADVANCED",
            reason="CANARY_5",
            actor=actor,
            actor_id=actor_id,
        )
        return result

    def advance(
        self,
        release_id: str,
        *,
        expected_version: int,
        actor: str,
        actor_id: str,
        target_stage: str,
        reason: str,
    ) -> AgentRelease:
        release = self._get(release_id)
        self._assert_previous_stack(release)
        next_stage = {
            AgentReleaseStatus.CANARY_5: AgentReleaseStatus.CANARY_25,
            AgentReleaseStatus.CANARY_25: AgentReleaseStatus.CANARY_50,
            AgentReleaseStatus.CANARY_50: AgentReleaseStatus.FULL,
        }.get(release.status)
        if next_stage is None or next_stage.value != target_stage:
            raise AgentReleasePolicyError("INVALID_STATE")
        _validate_observation_guardrail(release.observations)
        updated = replace(
            release,
            status=next_stage,
            version=expected_version + 1,
            updated_at=self._now(),
            observations={},
        )
        result = self._releases.update_release(
            updated, expected_version=expected_version
        )
        self._audit_event(
            result, "ROLLOUT_ADVANCED", reason=reason, actor=actor, actor_id=actor_id
        )
        return result

    def rollback(
        self,
        release_id: str,
        *,
        expected_version: int,
        actor: str,
        actor_id: str,
        reason: str,
    ) -> AgentRelease:
        release = self._get(release_id)
        if release.status in {
            AgentReleaseStatus.ROLLED_BACK,
            AgentReleaseStatus.REJECTED,
            AgentReleaseStatus.FAILED,
        }:
            raise AgentReleasePolicyError("INVALID_STATE")
        updated = replace(
            release,
            status=AgentReleaseStatus.ROLLED_BACK,
            version=expected_version + 1,
            updated_at=self._now(),
            rollback_reason=reason.strip(),
        )
        result = self._releases.update_release(
            updated, expected_version=expected_version
        )
        self._audit_event(
            result, "ROLLED_BACK", reason=reason, actor=actor, actor_id=actor_id
        )
        return result

    def _get(self, release_id: str) -> AgentRelease:
        release = self._releases.get_release(release_id)
        if release is None:
            raise AgentReleasePolicyError("RELEASE_NOT_FOUND")
        return release

    def _assert_previous_stack(self, release: AgentRelease) -> None:
        try:
            active = self._components.active_baseline()
        except ValueError as error:
            raise AgentReleasePolicyError("ACTIVE_STACK_CHANGED") from error
        if not _same_pins(active, release.previous_component_pins):
            raise AgentReleasePolicyError("ACTIVE_STACK_CHANGED")
        if any(
            self._components.resolve(pin) is None
            for pin in release.candidate_component_pins
        ):
            raise AgentReleasePolicyError("COMPONENT_PIN_INVALID")

    def _audit_event(
        self,
        release: AgentRelease,
        status: str,
        *,
        reason: str | None = None,
        actor: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        self._audit.append(
            AgentAuditEvent(
                session_id=release.session_id,
                occurred_at=self._now(),
                event_id=self._new_id(),
                category="release",
                status=status,
                reason_code=None,
                actor=actor,
                actor_id=actor_id,
                entity_id=release.release_id,
                version=release.version,
                snapshot_id=release.snapshot_id,
                content_sha256=release.snapshot_sha256,
                policy_version=release.rollout_policy_version,
                reason=reason,
            )
        )
        self._timeline_event(release, status, actor_id)

    def _timeline_event(
        self, release: AgentRelease, status: str, actor_id: str | None
    ) -> None:
        if self._timeline is None:
            return
        refs = {"release_id": release.release_id, "snapshot_id": release.snapshot_id}
        if status in _PRODUCTION_STATUSES:
            self._timeline.record_production_change(
                release.session_id,
                action=f"agent.release.{status.lower()}",
                entity_type="agent_release",
                entity_id=release.release_id,
                actor_id=actor_id or "system",
                outcome="success",
                summary=_PRODUCTION_STATUSES[status],
                refs=refs,
                correlation_id=release.release_id,
            )
            return
        self._timeline.record(
            release.session_id,
            AgentEventKind.USER_ACTION,
            AgentEventOutcome.INFO,
            "Release solicitado"
            if status == "RELEASE_REQUESTED"
            else "Modo sombra iniciado",
            refs=refs,
            actor_id=actor_id,
        )


def _validate_observation_guardrail(observations: dict) -> None:
    count = int(observations.get("count", 0))
    disagreements = int(observations.get("disagreements", 0))
    if (
        count < _MINIMUM_STAGE_OBSERVATIONS
        or disagreements < 0
        or disagreements > count
        or disagreements * 100 > count * _MAXIMUM_DECISION_DISAGREEMENT_PCT
    ):
        raise AgentReleasePolicyError("GUARDRAIL_NOT_MET")


def _same_pins(left, right) -> bool:
    return {pin.component: pin for pin in left} == {pin.component: pin for pin in right}
