from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from src.application.ports.agent_audit_port import AgentAuditEvent, AgentAuditRepository
from src.application.ports.agent_experiment_evaluator_port import (
    AgentExperimentEvaluator,
)
from src.application.ports.agent_experiment_port import AgentExperimentRepository
from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.agent_release_port import AgentReleaseRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_snapshot_port import DatasetSnapshotRepository
from src.application.use_cases.agent.evaluate_agent_experiment import (
    AgentExperimentPolicyError,
    _validate_runner_evidence,
    evaluate_global_constraints,
)
from src.domain.agents.experiment import AgentExperimentStatus
from src.domain.agents.release import (
    RetrospectiveValidation,
    RetrospectiveValidationStatus,
)
from src.domain.datasets.mature_sampling import content_hash

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PIN_TYPES = {"configuration", "library", "model", "vector_store"}


class RetrospectiveValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RetrospectiveValidationInput:
    session_id: str
    experiment_id: str
    actor: str
    actor_id: str


class ValidateRetrospectiveReleaseUseCase:
    def __init__(
        self,
        *,
        experiments: AgentExperimentRepository,
        releases: AgentReleaseRepository,
        snapshots: DatasetSnapshotRepository,
        datasets: DatasetRepository,
        objectives: AgentObjectiveRepository,
        evaluator: AgentExperimentEvaluator,
        audit: AgentAuditRepository,
        now: Callable,
        new_id: Callable,
    ) -> None:
        self._experiments = experiments
        self._releases = releases
        self._snapshots = snapshots
        self._datasets = datasets
        self._objectives = objectives
        self._evaluator = evaluator
        self._audit = audit
        self._now = now
        self._new_id = new_id

    def execute(self, request: RetrospectiveValidationInput) -> RetrospectiveValidation:
        experiment = self._experiments.get(request.session_id, request.experiment_id)
        if experiment is None:
            raise RetrospectiveValidationError("EXPERIMENT_NOT_FOUND")
        try:
            self._validate(experiment)
            snapshot = self._snapshots.get(experiment.snapshot_id or "")
            if (
                snapshot is None
                or snapshot.content_hash != experiment.snapshot_sha256
                or "final" not in snapshot.dataset_refs
                or "all" not in snapshot.dataset_refs
            ):
                raise RetrospectiveValidationError("SNAPSHOT_INVALID")
            partitions = {
                name: self._datasets.get_rows(snapshot.dataset_refs[name])
                for name in ("training", "validation", "test", "final")
            }
            all_rows = self._datasets.get_rows(snapshot.dataset_refs["all"])
            if any(
                len(partitions[name]) != snapshot.partition_counts.get(name)
                for name in ("training", "validation", "test", "final")
            ) or not partitions["final"]:
                raise RetrospectiveValidationError("SNAPSHOT_INVALID")
            if content_hash({**partitions, "all": all_rows}) != snapshot.content_hash:
                raise RetrospectiveValidationError("SNAPSHOT_INVALID")
            objective = self._objectives.get(
                experiment.objective_id, experiment.objective_version
            )
            if objective is None:
                raise RetrospectiveValidationError("OBJECTIVE_NOT_FOUND")
            refreshed = self._evaluator.evaluate(
                components=experiment.components,
                baseline_components=experiment.baseline_components,
                snapshot=snapshot,
                final_rows=partitions["final"],
                objective_id=experiment.objective_id,
                objective_version=experiment.objective_version,
            )
            _validate_runner_evidence(
                refreshed,
                experiment.components,
                experiment.baseline_components,
                objective,
                snapshot_id=experiment.snapshot_id or "",
                snapshot_sha256=experiment.snapshot_sha256 or "",
            )
            protected_evidence, passed = evaluate_global_constraints(
                objective, refreshed
            )
            if not passed:
                raise RetrospectiveValidationError("VALIDATION_FAILED")
        except RetrospectiveValidationError as error:
            self._append_audit(
                request,
                "RETROSPECTIVE_FAILED",
                error_code=str(error),
                snapshot_id=experiment.snapshot_id,
                content_sha256=experiment.snapshot_sha256,
                entity_id=experiment.experiment_id,
            )
            raise
        except (AgentExperimentPolicyError, FileNotFoundError, KeyError, OSError) as error:
            self._append_audit(
                request,
                "RETROSPECTIVE_FAILED",
                error_code="SNAPSHOT_INVALID",
                snapshot_id=experiment.snapshot_id,
                content_sha256=experiment.snapshot_sha256,
                entity_id=experiment.experiment_id,
            )
            raise RetrospectiveValidationError("SNAPSHOT_INVALID") from error
        except ValueError as error:
            self._append_audit(
                request,
                "RETROSPECTIVE_FAILED",
                error_code="VALIDATION_FAILED",
                snapshot_id=experiment.snapshot_id,
                content_sha256=experiment.snapshot_sha256,
                entity_id=experiment.experiment_id,
            )
            raise RetrospectiveValidationError("VALIDATION_FAILED") from error
        validation = RetrospectiveValidation(
            validation_id=self._new_id(),
            session_id=experiment.session_id,
            experiment_id=experiment.experiment_id,
            status=RetrospectiveValidationStatus.PASSED,
            snapshot_id=experiment.snapshot_id or "",
            snapshot_sha256=experiment.snapshot_sha256 or "",
            component_pins=experiment.components,
            baseline_component_pins=experiment.baseline_components,
            evidence=protected_evidence,
            created_by=request.actor,
            created_by_id=request.actor_id,
            created_at=self._now(),
        )
        self._releases.create_validation(validation)
        self._append_audit(
            request,
            "RETROSPECTIVE_PASSED",
            snapshot_id=validation.snapshot_id,
            content_sha256=validation.snapshot_sha256,
            entity_id=validation.experiment_id,
        )
        return validation

    @staticmethod
    def _validate(experiment) -> None:
        if experiment.status is not AgentExperimentStatus.SUCCEEDED:
            raise RetrospectiveValidationError("EXPERIMENT_NOT_SUCCEEDED")
        if (
            not experiment.snapshot_id
            or not _SHA256.fullmatch(experiment.snapshot_sha256 or "")
        ):
            raise RetrospectiveValidationError("SNAPSHOT_INVALID")
        evidence = experiment.global_evaluation
        sample = evidence.get("sample")
        if (
            not isinstance(sample, dict)
            or sample.get("snapshot_id") != experiment.snapshot_id
            or sample.get("content_sha256") != experiment.snapshot_sha256
            or sample.get("partition") != "final"
        ):
            raise RetrospectiveValidationError("SNAPSHOT_INVALID")
        if evidence.get("status") != "PASSED":
            raise RetrospectiveValidationError("VALIDATION_FAILED")
        constraints = evidence.get("constraints")
        if (
            not isinstance(constraints, list)
            or not constraints
            or any(
                not isinstance(item, dict) or item.get("status") != "PASSED"
                for item in constraints
            )
        ):
            raise RetrospectiveValidationError("VALIDATION_FAILED")
        if not _valid_pins(experiment.components) or not _valid_pins(
            experiment.baseline_components
        ):
            raise RetrospectiveValidationError("COMPONENT_PIN_INVALID")

    def _append_audit(
        self,
        request: RetrospectiveValidationInput,
        action: str,
        *,
        error_code: str | None = None,
        snapshot_id: str | None = None,
        content_sha256: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        self._audit.append(
            AgentAuditEvent(
                session_id=request.session_id,
                occurred_at=self._now(),
                event_id=self._new_id(),
                category="release",
                status=action,
                reason_code=error_code,
                actor=request.actor,
                actor_id=request.actor_id,
                entity_id=entity_id or request.experiment_id,
                snapshot_id=snapshot_id,
                content_sha256=content_sha256,
            )
        )


def _valid_pins(pins) -> bool:
    return (
        {pin.component for pin in pins} == _PIN_TYPES
        and len(pins) == len(_PIN_TYPES)
        and all(_SHA256.fullmatch(pin.content_sha256) for pin in pins)
    )
