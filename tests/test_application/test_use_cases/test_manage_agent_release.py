from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.application.use_cases.agent.manage_agent_release import (
    AgentReleasePolicyError,
    ManageAgentReleaseUseCase,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.release import (
    AgentReleaseStatus,
    RetrospectiveValidation,
    RetrospectiveValidationStatus,
)


def _pins(version: str) -> tuple[ComponentVersionReference, ...]:
    return tuple(
        ComponentVersionReference.pin(
            component, f"{component}-{version}", version, {"version": version}
        )
        for component in ("model", "configuration", "library", "vector_store")
    )


def _model_only_candidate() -> tuple[ComponentVersionReference, ...]:
    baseline = _pins("baseline")
    return (_pins("candidate")[0], *baseline[1:])


class _Releases:
    def __init__(self):
        self.validation = RetrospectiveValidation(
            validation_id="validation-1",
            session_id="session-1",
            experiment_id="experiment-1",
            status=RetrospectiveValidationStatus.PASSED,
            snapshot_id="snapshot-1",
            snapshot_sha256="a" * 64,
            component_pins=_model_only_candidate(),
            baseline_component_pins=_pins("baseline"),
            evidence={},
            created_by="requester",
            created_by_id="channel-manager",
            created_at=datetime(2026, 10, 21, tzinfo=UTC),
        )
        self.release = None
        self.observations = []

    def get_validation(self, validation_id):
        return self.validation if validation_id == self.validation.validation_id else None

    def list_releases(self, limit=100, statuses=None):
        if self.release is None:
            return []
        if statuses is not None and self.release.status.value not in statuses:
            return []
        return [self.release]

    def create_release(self, release):
        if self.release is not None:
            raise ValueError("ACTIVE_RELEASE_EXISTS")
        self.release = release
        return release

    def get_release(self, release_id):
        return self.release if self.release and self.release.release_id == release_id else None

    def update_release(self, release, *, expected_version):
        if self.release.version != expected_version:
            raise ValueError("VERSION_CONFLICT")
        self.release = release
        return release


class _Components:
    def __init__(self):
        # The resolver emits its own stable ordering; pin tuples are identified
        # by component, not by tuple position.
        self.active = tuple(reversed(_pins("baseline")))

    def active_baseline(self):
        return self.active

    def resolve(self, reference):
        return object()


class _Audit:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


def _use_case():
    releases = _Releases()
    components = _Components()
    audit = _Audit()
    use_case = ManageAgentReleaseUseCase(
        releases=releases,
        components=components,
        audit=audit,
        now=lambda: datetime(2026, 10, 21, tzinfo=UTC),
        new_id=lambda: "release-1",
    )
    return use_case, releases, components, audit


def test_release_requires_shadow_observations_and_distinct_manager_approval():
    use_case, releases, _, audit = _use_case()
    release = use_case.request(
        validation_id="validation-1",
        title="Candidate rollout",
        reason="Retrospective validation completed",
        actor="requester",
        actor_id="channel-manager",
    )
    assert release.status is AgentReleaseStatus.SHADOW
    assert [event.status for event in audit.events] == [
        "RELEASE_REQUESTED",
        "SHADOW_STARTED",
    ]

    with pytest.raises(AgentReleasePolicyError, match="GUARDRAIL_NOT_MET"):
        use_case.submit_for_approval(
            "release-1", expected_version=1, actor="requester", actor_id="channel-manager", reason="Review"
        )

    releases.release = replace(release, observations={"count": 30, "disagreements": 0})
    submitted = use_case.submit_for_approval(
        "release-1", expected_version=1, actor="requester", actor_id="channel-manager", reason="Review complete"
    )
    with pytest.raises(AgentReleasePolicyError, match="SELF_APPROVAL"):
        use_case.approve(
            "release-1",
            expected_version=submitted.version,
            actor="requester",
            actor_id="channel-manager",
            reason="Approve",
        )

    approved = use_case.approve(
        "release-1",
        expected_version=submitted.version,
        actor="approver",
        actor_id="manager",
        reason="Approved after review",
    )
    assert approved.status is AgentReleaseStatus.CANARY_5


def test_rollout_requires_minimum_observations_and_rollback_releases_active_slot():
    use_case, releases, _, _ = _use_case()
    release = use_case.request(
        validation_id="validation-1",
        title="Candidate rollout",
        reason="Retrospective validation completed",
        actor="requester",
        actor_id="channel-manager",
    )
    releases.release = replace(
        release,
        status=AgentReleaseStatus.CANARY_5,
        approved_by_id="manager",
        observations={"count": 29},
    )
    with pytest.raises(AgentReleasePolicyError, match="GUARDRAIL_NOT_MET"):
        use_case.advance(
            "release-1",
            expected_version=1,
            actor="manager",
            actor_id="manager",
            target_stage=AgentReleaseStatus.CANARY_25.value,
            reason="Advance",
        )
    releases.release = replace(
        releases.release, observations={"count": 30, "disagreements": 2}
    )
    with pytest.raises(AgentReleasePolicyError, match="GUARDRAIL_NOT_MET"):
        use_case.advance(
            "release-1",
            expected_version=1,
            actor="manager",
            actor_id="manager",
            target_stage=AgentReleaseStatus.CANARY_25.value,
            reason="Disagreement exceeds policy",
        )
    rolled_back = use_case.rollback(
        "release-1",
        expected_version=1,
        actor="manager",
        actor_id="manager",
        reason="Guardrail did not pass",
    )
    assert rolled_back.status is AgentReleaseStatus.ROLLED_BACK
    assert rolled_back.rollback_reason == "Guardrail did not pass"


def test_release_rejects_non_model_component_changes():
    use_case, releases, _, _ = _use_case()
    validation = releases.validation
    releases.validation = replace(
        validation,
        component_pins=(
            validation.component_pins[0],
            _pins("candidate-config")[1],
            validation.component_pins[2],
            validation.component_pins[3],
        ),
    )
    with pytest.raises(AgentReleasePolicyError, match="UNSUPPORTED_COMPONENT_ROLLOUT"):
        use_case.request(
            validation_id="validation-1",
            title="Candidate rollout",
            reason="Retrospective validation completed",
            actor="requester",
            actor_id="channel-manager",
        )
