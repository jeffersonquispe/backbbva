from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from src.application.ports.agent_release_port import AgentReleaseRepository
from src.application.ports.agent_session_port import (
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.configuration_deploy_request_port import (
    ConfigurationDeployRequestRepository,
)
from src.application.ports.configuration_port import ConfigurationRepository
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.optimization_run_port import OptimizationRunRepository
from src.application.ports.test_run_port import TestRunRepository
from src.application.ports.vector_store_generation_port import (
    VectorStoreGenerationRepository,
    VectorStoreGenerationStatus,
)
from src.application.runtime_defaults import resolve_clock
from src.domain.agents.release import AgentReleaseStatus
from src.domain.test_runs.entities import TestRunStatus

# A build normally takes seconds; one still BUILDING after this crashed
# mid-way and would otherwise block every later build of its instance.
STALE_BUILD_AFTER = timedelta(hours=1)

_OPEN_RELEASE_STATUSES = {
    AgentReleaseStatus.SHADOW.value,
    AgentReleaseStatus.PENDING_APPROVAL.value,
    AgentReleaseStatus.CANARY_5.value,
    AgentReleaseStatus.CANARY_25.value,
    AgentReleaseStatus.CANARY_50.value,
}
_OPEN_TEST_RUN_STATUSES = {TestRunStatus.PENDING, TestRunStatus.RUNNING}


@dataclass(frozen=True)
class CleanupVectorStoreGenerationsOutput:
    retired: tuple[str, ...]
    protected: int
    failed_stale_builds: tuple[str, ...]
    deleted_documents: int
    dry_run: bool


class CleanupVectorStoreGenerationsUseCase:
    """Retires READY generations nothing can still search.

    Protected, never retired:
    - generations pinned by the active configuration and by the
      ``rollback_configurations`` versions active before it;
    - generations pinned by the target of a pending deploy request;
    - generations pinned by the configuration of a pending/running test;
    - generations pinned by an open agent release (shadow, approval,
      canary);
    - generations built less than ``retention_days`` ago - this also covers
      optimizer sessions and configuration drafts that are still in use.

    Retiring deletes the generation's OpenSearch documents and keeps its
    record as RETIRED, so a configuration still pinning it fails with a
    clear reason when tested or activated.
    """

    def __init__(
        self,
        *,
        generations: VectorStoreGenerationRepository,
        configurations: ConfigurationRepository,
        deploy_requests: ConfigurationDeployRequestRepository,
        test_runs: TestRunRepository,
        releases: AgentReleaseRepository,
        sessions: AgentSessionRepository,
        optimization_runs: OptimizationRunRepository,
        fraud_knowledge_repository: FraudKnowledgeRepository,
        clock: Clock | None = None,
    ) -> None:
        self._generations = generations
        self._configurations = configurations
        self._deploy_requests = deploy_requests
        self._test_runs = test_runs
        self._releases = releases
        self._sessions = sessions
        self._optimization_runs = optimization_runs
        self._fraud_knowledge_repository = fraud_knowledge_repository
        self._clock = resolve_clock(clock)

    def execute(
        self,
        *,
        retention_days: int,
        rollback_configurations: int,
        dry_run: bool = False,
        instance_id: str | None = None,
    ) -> CleanupVectorStoreGenerationsOutput:
        """``instance_id`` limits the sweep to one instance (an operator
        cleaning up one store); protections are always computed globally."""
        now = self._clock.now()
        protected = self.protected_pins(rollback_configurations)
        retired: list[str] = []
        failed: list[str] = []
        deleted = 0
        kept = 0
        for generation in self._generations.list(instance_id):
            key = (generation.instance_id, generation.generation)
            label = f"{generation.instance_id}@g{generation.generation}"
            if generation.status == VectorStoreGenerationStatus.BUILDING:
                if now - generation.created_at < STALE_BUILD_AFTER:
                    continue
                failed.append(label)
                if not dry_run:
                    deleted += self._fraud_knowledge_repository.delete_generation(
                        *key
                    )
                    self._generations.update(
                        replace(
                            generation,
                            status=VectorStoreGenerationStatus.FAILED,
                            error="STALE_BUILD",
                        )
                    )
                continue
            if generation.status == VectorStoreGenerationStatus.FAILED:
                if not dry_run and now - generation.created_at >= STALE_BUILD_AFTER:
                    deleted += self._fraud_knowledge_repository.delete_generation(*key)
                continue
            if generation.status != VectorStoreGenerationStatus.READY:
                continue
            built_at = generation.ready_at or generation.created_at
            if key in protected or now - built_at < timedelta(days=retention_days):
                kept += 1
                continue
            retired.append(label)
            if not dry_run:
                deleted += self._fraud_knowledge_repository.delete_generation(*key)
                self._generations.update(
                    replace(
                        generation,
                        status=VectorStoreGenerationStatus.RETIRED,
                        retired_at=now,
                    )
                )
        return CleanupVectorStoreGenerationsOutput(
            retired=tuple(retired),
            protected=kept,
            failed_stale_builds=tuple(failed),
            deleted_documents=deleted,
            dry_run=dry_run,
        )

    def protected_pins(self, rollback_configurations: int) -> set[tuple[str, int]]:
        # list_all_versions() rows carry no segments: they only say which
        # versions to protect; their pins come from list_vector_store_pins().
        versions = self._configurations.list_all_versions()
        keep: list[tuple[str, int]] = [
            (item.configuration_id, item.version)
            for item in sorted(
                (item for item in versions if item.active or item.ever_activated),
                key=lambda item: (item.active, item.activated_at or item.created_at),
                reverse=True,
            )[: 1 + max(0, rollback_configurations)]
        ]
        for request in self._deploy_requests.list():
            if request.status == "pending":
                keep.append((request.target_configuration_id, request.target_version))
        for run in self._test_runs.list():
            ref = run.config.configuration_ref
            if run.status in _OPEN_TEST_RUN_STATUSES and ref is not None:
                keep.append((ref.configuration_id, ref.version or 0))

        saved_pins = self._configurations.list_vector_store_pins()
        pins: set[tuple[str, int]] = {
            (pin.instance_id, pin.generation)
            for key in keep
            for pin in saved_pins.get(key, set())
            if pin.generation is not None
        }
        for release in self._releases.list_releases(
            limit=200, statuses=_OPEN_RELEASE_STATUSES
        ):
            for component in (
                *release.candidate_component_pins,
                *release.previous_component_pins,
            ):
                if component.component == "vector_store":
                    try:
                        pins.add((component.entity_id, int(component.version)))
                    except ValueError:
                        continue
        closed = {AgentSessionStatus.COMPLETED, AgentSessionStatus.STOPPED,
                  AgentSessionStatus.CANCELLED, AgentSessionStatus.FAILED}
        for status in AgentSessionStatus:
            if status in closed:
                continue
            for session in self._sessions.list_by_status(status, limit=None):
                references = list(session.baseline_components)
                tree = self._optimization_runs.load_tree(session.session_id)
                if tree is not None:
                    references.extend(tree.root.baseline_components)
                    references.extend(tree.root.winning_components)
                    experiments = [view.experiment for view in tree.unassigned_experiments]
                    for candidate in tree.candidates:
                        experiments.extend(view.experiment for view in candidate.experiments)
                    for experiment in experiments:
                        references.extend(experiment.components)
                        references.extend(experiment.baseline_components)
                for component in references:
                    if component.component == "vector_store":
                        try:
                            pins.add((component.entity_id, int(component.version)))
                        except ValueError:
                            continue
        return pins
