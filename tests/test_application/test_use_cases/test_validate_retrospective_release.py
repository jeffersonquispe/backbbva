from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.application.use_cases.agent.validate_retrospective_release import (
    RetrospectiveValidationError,
    RetrospectiveValidationInput,
    ValidateRetrospectiveReleaseUseCase,
)
from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.domain.agents.release import RetrospectiveValidationStatus

NOW = datetime(2026, 10, 26, tzinfo=UTC)
SHA = "a" * 64


def _pins(version):
    return tuple(
        ComponentVersionReference.pin(
            name, f"{name}-{version}", version, {"v": version}
        )
        for name in ("model", "configuration", "library", "vector_store")
    )


def _experiment(status=AgentExperimentStatus.SUCCEEDED):
    return AgentExperiment(
        session_id="s1",
        experiment_id="e1",
        iteration_number=1,
        kind=AgentExperimentKind.ISOLATED,
        status=status,
        components=_pins("2"),
        baseline_components=_pins("1"),
        objective_id="o1",
        objective_version=1,
        created_at=NOW,
        snapshot_id="snap-1",
        snapshot_sha256=SHA,
        global_evaluation={
            "status": "PASSED",
            "sample": {
                "snapshot_id": "snap-1",
                "content_sha256": SHA,
                "partition": "final",
            },
            "constraints": [{"status": "PASSED"}],
        },
    )


class Experiments:
    def __init__(self, experiment):
        self.experiment = experiment

    def get(self, session_id, experiment_id):
        return self.experiment


class Releases:
    def __init__(self):
        self.validations = {}

    def create_validation(self, validation):
        self.validations[validation.validation_id] = validation
        return validation

    def get_validation(self, validation_id):
        return self.validations.get(validation_id)

    def update_validation(self, validation, *, expected_status):
        assert (
            self.validations[validation.validation_id].status.value == expected_status
        )
        self.validations[validation.validation_id] = validation
        return validation


class Missing:
    def get(self, *args):
        return None


class Audit:
    def __init__(self):
        self.statuses = []

    def append(self, event):
        self.statuses.append((event.status, event.reason_code))


def _use_case(experiment):
    releases, audit = Releases(), Audit()
    use_case = ValidateRetrospectiveReleaseUseCase(
        experiments=Experiments(experiment),
        releases=releases,
        snapshots=Missing(),
        datasets=Missing(),
        objectives=Missing(),
        evaluator=Missing(),
        audit=audit,
        now=lambda: NOW,
        new_id=lambda: "val-1",
    )
    return use_case, releases, audit


REQUEST = RetrospectiveValidationInput("s1", "e1", "cm", "cm-1")


def test_start_records_a_running_validation_and_leaves_the_replay_for_later():
    use_case, releases, audit = _use_case(_experiment())

    validation = use_case.start(REQUEST)

    assert validation.status is RetrospectiveValidationStatus.RUNNING
    assert releases.validations["val-1"].component_pins == _pins("2")
    assert audit.statuses == [("RETROSPECTIVE_STARTED", None)]


def test_start_refuses_an_experiment_that_did_not_succeed():
    use_case, releases, audit = _use_case(_experiment(AgentExperimentStatus.FAILED))

    with pytest.raises(RetrospectiveValidationError, match="EXPERIMENT_NOT_SUCCEEDED"):
        use_case.start(REQUEST)

    assert releases.validations == {}
    assert audit.statuses == [("RETROSPECTIVE_FAILED", "EXPERIMENT_NOT_SUCCEEDED")]


def test_complete_marks_failures_with_their_safe_code():
    use_case, releases, _ = _use_case(_experiment())
    use_case.start(REQUEST)

    finished = use_case.complete("val-1")

    assert finished.status is RetrospectiveValidationStatus.FAILED
    assert finished.error_code == "SNAPSHOT_INVALID"


def test_complete_passes_with_the_refreshed_evidence_and_is_idempotent():
    use_case, releases, audit = _use_case(_experiment())
    use_case.start(REQUEST)
    use_case._measure = lambda request, experiment: {"precision": 0.95}  # type: ignore[method-assign]

    finished = use_case.complete("val-1")
    again = use_case.complete("val-1")

    assert finished.status is RetrospectiveValidationStatus.PASSED
    assert finished.evidence == {"precision": 0.95}
    assert again == finished
    assert ("RETROSPECTIVE_PASSED", None) in audit.statuses


def test_complete_of_an_unknown_validation_returns_none():
    use_case, _, _ = _use_case(_experiment())

    assert use_case.complete("nope") is None


def test_running_validations_cannot_be_released():
    from src.application.use_cases.agent.manage_agent_release import (
        AgentReleasePolicyError,
        ManageAgentReleaseUseCase,
    )

    use_case, releases, _ = _use_case(_experiment())
    running = use_case.start(REQUEST)

    class ReleaseRepo(Releases):
        def __init__(self, validations):
            super().__init__()
            self.validations = validations

    manage = ManageAgentReleaseUseCase(
        releases=ReleaseRepo(releases.validations),
        components=None,
        audit=Audit(),
        now=lambda: NOW,
        new_id=lambda: "rel",
    )
    with pytest.raises(AgentReleasePolicyError, match="VALIDATION_FAILED"):
        manage.request(
            validation_id=running.validation_id,
            title="x",
            reason="x",
            actor="cm",
            actor_id="cm-1",
        )
    assert replace(running).status is RetrospectiveValidationStatus.RUNNING
