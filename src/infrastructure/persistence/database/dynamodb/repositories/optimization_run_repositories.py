"""`optimization_runs`: the single structure of an optimizer run.

Root, candidates (hypotheses with their conclusion), experiments and findings
share one partition, so the whole run is read with one query. The ports the
orchestrator already uses (hypotheses, experiments, findings) are implemented
on top of it, so there are no parallel tables.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.agent_experiment_port import AgentExperimentRepository
from src.application.ports.agent_finding_port import AgentFindingRepository
from src.application.ports.agent_hypothesis_port import (
    AgentHypothesis,
    AgentHypothesisRepository,
    AgentHypothesisStatus,
)
from src.application.ports.optimization_run_port import OptimizationRunRepository
from src.domain.agents.experiment import AgentExperiment, ComponentVersionReference
from src.domain.agents.finding import AgentFinding
from src.domain.agents.optimization_run import (
    OptimizationRun,
    OptimizationRunStatus,
    OptimizationRunTree,
    RunCandidateView,
    RunExperimentView,
    RunWinner,
    experiment_stream_key,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_event_repositories import (
    finding_from_item,
    finding_to_item,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_repositories import (
    AgentRecordConflictError,
    _component_pins_hash,
    _encode,
    _experiment,
    _experiment_item,
    _raise_if_conflict,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    OPTIMIZATION_RUNS_TABLE,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

ROOT = "RUN"
CANDIDATE = "CAND#"
EXPERIMENT = "EXP#"
FINDING = "FIND#"


def _table():
    return get_dynamodb_resource().Table(OPTIMIZATION_RUNS_TABLE["TableName"])


def _query_all(run_id: str, prefix: str | None = None) -> list[dict[str, Any]]:
    table = _table()
    condition = Key("run_id").eq(run_id)
    if prefix:
        condition = condition & Key("node").begins_with(prefix)
    kwargs: dict[str, Any] = {"KeyConditionExpression": condition}
    items: list[dict[str, Any]] = []
    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        last = response.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs["ExclusiveStartKey"] = last


def _strip_keys(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key not in {"run_id", "node"}}


# ---------------------------------------------------------------- root node
def run_to_item(run: OptimizationRun) -> dict[str, Any]:
    data = asdict(run)
    data["status"] = run.status.value
    data["created_at"] = run.created_at.isoformat()
    data["updated_at"] = run.updated_at.isoformat()
    data["baseline_components"] = [asdict(pin) for pin in run.baseline_components]
    data["winning_components"] = [asdict(pin) for pin in run.winning_components]
    data["winners"] = [asdict(winner) for winner in run.winners]
    data["scope_areas"] = list(run.scope_areas)
    data["insight_ids"] = list(run.insight_ids)
    data["memory_insight_ids"] = list(run.memory_insight_ids)
    data["node"] = ROOT
    return to_dynamodb({key: value for key, value in data.items() if value is not None})


def run_from_item(item: dict[str, Any]) -> OptimizationRun:
    row = from_dynamodb(_strip_keys(item))
    row["run_id"] = item["run_id"]
    return OptimizationRun(
        run_id=row["run_id"],
        status=OptimizationRunStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        objective_id=row.get("objective_id"),
        objective_version=row.get("objective_version"),
        baseline_components=tuple(
            ComponentVersionReference(**pin)
            for pin in row.get("baseline_components", [])
        ),
        budget_limits=dict(row.get("budget_limits", {})),
        optimizer_settings=dict(row.get("optimizer_settings", {})),
        scope_areas=tuple(row.get("scope_areas", [])),
        insight_ids=tuple(row.get("insight_ids", [])),
        memory_insight_ids=tuple(row.get("memory_insight_ids", [])),
        winners=tuple(RunWinner(**winner) for winner in row.get("winners", [])),
        winning_components=tuple(
            ComponentVersionReference(**pin)
            for pin in row.get("winning_components", [])
        ),
        strategy=dict(row.get("strategy", {})),
        events_stream=row.get("events_stream", ""),
        rev=int(row.get("rev", 0)),
    )


# ---------------------------------------------------------- candidate nodes
def hypothesis_to_item(hypothesis: AgentHypothesis) -> dict[str, Any]:
    data = asdict(hypothesis)
    data["status"] = hypothesis.status.value
    data["depends_on"] = list(hypothesis.depends_on)
    data["insight_ids"] = list(hypothesis.insight_ids)
    data["run_id"] = hypothesis.session_id
    data["node"] = f"{CANDIDATE}{hypothesis.hypothesis_id}"
    return _encode(data)


def hypothesis_from_item(item: dict[str, Any]) -> AgentHypothesis:
    row = from_dynamodb(_strip_keys(item))
    return AgentHypothesis(
        session_id=row["session_id"],
        hypothesis_id=row["hypothesis_id"],
        statement=row["statement"],
        scope=dict(row.get("scope", {})),
        priority=int(row.get("priority", 0)),
        status=AgentHypothesisStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        source_insight_id=row.get("source_insight_id"),
        evidence_id=row.get("evidence_id"),
        evidence_outcome=row.get("evidence_outcome"),
        rev=int(row.get("rev", 0)),
        depends_on=tuple(row.get("depends_on", [])),
        insight_ids=tuple(row.get("insight_ids", [])),
        conclusion=dict(row.get("conclusion", {})),
    )


def experiment_to_item(experiment: AgentExperiment) -> dict[str, Any]:
    data = _experiment_item(experiment)
    data["run_id"] = experiment.session_id
    data["node"] = f"{EXPERIMENT}{experiment.experiment_id}"
    data["events_stream"] = experiment_stream_key(
        experiment.session_id, experiment.experiment_id
    )
    return _encode(data)


def experiment_from_item(item: dict[str, Any]) -> AgentExperiment:
    row = _strip_keys(item)
    row.pop("events_stream", None)
    experiment = _experiment(row)
    candidate = item.get("candidate_id")
    return replace(experiment, candidate_id=str(candidate)) if candidate else experiment


class DynamoOptimizationRunRepository(OptimizationRunRepository):
    def get(self, run_id: str) -> OptimizationRun | None:
        item = _table().get_item(Key={"run_id": run_id, "node": ROOT}).get("Item")
        return run_from_item(item) if item else None

    def create_once(self, run: OptimizationRun) -> OptimizationRun:
        try:
            _table().put_item(
                Item=run_to_item(run), ConditionExpression="attribute_not_exists(node)"
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = self.get(run.run_id)
            if existing is not None:
                return existing
        return run

    def update(self, run: OptimizationRun, expected_rev: int) -> OptimizationRun:
        updated = replace(run, rev=expected_rev + 1)
        try:
            _table().put_item(
                Item=run_to_item(updated),
                ConditionExpression="rev = :expected",
                ExpressionAttributeValues={":expected": expected_rev},
            )
        except ClientError as error:
            _raise_if_conflict(error)
        return updated

    def load_tree(self, run_id: str) -> OptimizationRunTree | None:
        items = _query_all(run_id)
        root_item = next((item for item in items if item["node"] == ROOT), None)
        if root_item is None:
            return None
        hypotheses = [
            hypothesis_from_item(item)
            for item in items
            if str(item["node"]).startswith(CANDIDATE)
        ]
        experiments = [
            RunExperimentView(
                experiment=experiment_from_item(item),
                events_stream=str(item.get("events_stream", "")),
            )
            for item in items
            if str(item["node"]).startswith(EXPERIMENT)
        ]
        by_candidate: dict[str, list[RunExperimentView]] = {}
        for view in experiments:
            by_candidate.setdefault(view.experiment.candidate_id or "", []).append(view)
        known = {item.hypothesis_id for item in hypotheses}
        return OptimizationRunTree(
            root=run_from_item(root_item),
            candidates=tuple(
                RunCandidateView(
                    hypothesis=hypothesis,
                    experiments=tuple(
                        sorted(
                            by_candidate.get(hypothesis.hypothesis_id, []),
                            key=lambda view: view.experiment.created_at,
                        )
                    ),
                )
                for hypothesis in sorted(hypotheses, key=lambda item: item.created_at)
            ),
            unassigned_experiments=tuple(
                view
                for view in experiments
                if (view.experiment.candidate_id or "") not in known
            ),
            findings=tuple(
                finding_from_item(_strip_keys(item))
                for item in items
                if str(item["node"]).startswith(FINDING)
            ),
        )


class DynamoRunHypothesisRepository(AgentHypothesisRepository):
    """Candidates of an optimization run (`CAND#` nodes)."""

    def create(self, hypothesis: AgentHypothesis) -> AgentHypothesis:
        try:
            _table().put_item(
                Item=hypothesis_to_item(hypothesis),
                ConditionExpression="attribute_not_exists(node)",
            )
        except ClientError as error:
            _raise_if_conflict(error)
        return hypothesis

    def list_for_session(
        self, session_id: str, limit: int = 100
    ) -> list[AgentHypothesis]:
        return [
            hypothesis_from_item(item) for item in _query_all(session_id, CANDIDATE)
        ][:limit]

    def update(self, hypothesis: AgentHypothesis, expected_rev: int) -> AgentHypothesis:
        item = hypothesis_to_item(replace(hypothesis, rev=expected_rev + 1))
        try:
            _table().put_item(
                Item=item,
                ConditionExpression="rev = :expected AND #status = :active",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":expected": expected_rev,
                    ":active": AgentHypothesisStatus.ACTIVE.value,
                },
            )
        except ClientError as error:
            _raise_if_conflict(error)
        return hypothesis_from_item(item)


class DynamoRunExperimentRepository(AgentExperimentRepository):
    """Experiments of an optimization run (`EXP#` nodes), status-guarded."""

    def create(self, experiment: AgentExperiment) -> AgentExperiment:
        try:
            _table().put_item(
                Item=experiment_to_item(experiment),
                ConditionExpression="attribute_not_exists(node)",
            )
        except ClientError as error:
            _raise_if_conflict(error)
        return experiment

    def get(self, session_id: str, experiment_id: str) -> AgentExperiment | None:
        item = (
            _table()
            .get_item(
                Key={"run_id": session_id, "node": f"{EXPERIMENT}{experiment_id}"}
            )
            .get("Item")
        )
        return experiment_from_item(item) if item else None

    def list_for_session(
        self, session_id: str, limit: int = 50
    ) -> list[AgentExperiment]:
        experiments = [
            experiment_from_item(item) for item in _query_all(session_id, EXPERIMENT)
        ]
        return sorted(experiments, key=lambda item: item.created_at, reverse=True)[
            :limit
        ]

    def update(
        self, experiment: AgentExperiment, *, expected_status: str
    ) -> AgentExperiment:
        try:
            _table().put_item(
                Item=experiment_to_item(experiment),
                ConditionExpression=(
                    "#status = :expected AND component_pins_sha256 = :pins_hash AND "
                    "kind = :kind AND iteration_number = :iteration_number AND "
                    "objective_id = :objective_id AND "
                    "objective_version = :objective_version AND created_at = :created_at"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=to_dynamodb(
                    {
                        ":expected": expected_status,
                        ":pins_hash": _component_pins_hash(
                            experiment.components, experiment.baseline_components
                        ),
                        ":kind": experiment.kind.value,
                        ":iteration_number": experiment.iteration_number,
                        ":objective_id": experiment.objective_id,
                        ":objective_version": experiment.objective_version,
                        ":created_at": experiment.created_at.isoformat(),
                    }
                ),
            )
        except ClientError as error:
            _raise_if_conflict(error)
        return experiment


class DynamoRunFindingRepository(AgentFindingRepository):
    """Aggregated findings of an optimization run (`FIND#` nodes)."""

    def create_once(self, finding: AgentFinding) -> AgentFinding:
        item = {
            **finding_to_item(finding),
            "run_id": finding.session_id,
            "node": f"{FINDING}{finding.finding_id}",
        }
        try:
            _table().put_item(
                Item=item, ConditionExpression="attribute_not_exists(node)"
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = self.get(finding.session_id, finding.finding_id)
            if existing is not None:
                return existing
        return finding

    def get(self, session_id: str, finding_id: str) -> AgentFinding | None:
        item = (
            _table()
            .get_item(Key={"run_id": session_id, "node": f"{FINDING}{finding_id}"})
            .get("Item")
        )
        return finding_from_item(_strip_keys(item)) if item else None

    def list_for_session(self, session_id: str, limit: int = 100) -> list[AgentFinding]:
        return [
            finding_from_item(_strip_keys(item))
            for item in _query_all(session_id, FINDING)
        ][:limit]


__all__ = [
    "AgentRecordConflictError",
    "DynamoOptimizationRunRepository",
    "DynamoRunExperimentRepository",
    "DynamoRunFindingRepository",
    "DynamoRunHypothesisRepository",
]
