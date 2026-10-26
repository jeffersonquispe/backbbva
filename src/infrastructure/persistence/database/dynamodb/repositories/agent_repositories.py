from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.agent_budget_ledger_port import AgentBudgetEntry
from src.application.ports.agent_confirmation_port import AgentConfirmation
from src.application.ports.agent_entity_claim_port import AgentEntityClaim
from src.application.ports.agent_hypothesis_port import (
    AgentHypothesis,
    AgentHypothesisStatus,
)
from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationStatus,
)
from src.application.ports.agent_package_port import AgentPackage
from src.application.ports.agent_prompt_port import (
    ActiveAgentPrompt,
    AgentPrompt,
)
from src.application.ports.agent_run_port import AgentRun, AgentRunStatus
from src.application.ports.agent_tool_call_port import AgentToolCall
from src.application.ports.agent_verification_port import AgentVerification
from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)


class AgentRecordConflictError(Exception):
    """Raised when an immutable or revision-guarded record already changed."""


class DynamoAgentIterationRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_iterations")

    def create(self, iteration: AgentIteration) -> AgentIteration:
        item = _encode(asdict(iteration))
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(session_id) AND attribute_not_exists(#number)",
                ExpressionAttributeNames={"#number": "number"},
            )
        except ClientError as error:
            _raise_if_conflict(error)
        return iteration

    def get(self, session_id: str, number: int) -> AgentIteration | None:
        item = self._table.get_item(
            Key={"session_id": session_id, "number": number}
        ).get("Item")
        return _iteration(item) if item else None

    def list_for_session(
        self, session_id: str, limit: int = 50
    ) -> list[AgentIteration]:
        result = self._table.query(
            KeyConditionExpression=Key("session_id").eq(session_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_iteration(item) for item in result.get("Items", [])]

    def update(self, iteration: AgentIteration) -> AgentIteration:
        try:
            self._table.put_item(
                Item=_encode(asdict(iteration)),
                ConditionExpression="#status = :running",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":running": AgentIterationStatus.RUNNING.value
                },
            )
        except ClientError as error:
            _raise_if_conflict(error)
        return iteration


class DynamoAgentRunRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_runs")

    def create(self, run: AgentRun) -> AgentRun:
        self._table.put_item(
            Item=_encode(asdict(run)),
            ConditionExpression="attribute_not_exists(run_id)",
        )
        return run

    def get(self, run_id: str) -> AgentRun | None:
        item = self._table.get_item(Key={"run_id": run_id}).get("Item")
        return _run(item) if item else None

    def update(self, run: AgentRun) -> AgentRun:
        self._table.put_item(Item=_encode(asdict(run)))
        return run

    def extend_lease(self, run_id: str, until: datetime) -> bool:
        try:
            self._table.update_item(
                Key={"run_id": run_id},
                UpdateExpression="SET lease_expires_at = :until",
                ConditionExpression="#status = :running",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":until": until.isoformat(),
                    ":running": AgentRunStatus.RUNNING.value,
                },
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def list_active(self, now: datetime, limit: int = 100) -> list[AgentRun]:
        result = self._table.query(
            IndexName="StatusLeaseIdx",
            KeyConditionExpression=(
                Key("status").eq(AgentRunStatus.RUNNING.value)
                & Key("lease_expires_at").gt(now.isoformat())
            ),
            Limit=limit,
        )
        return [_run(item) for item in result.get("Items", [])]

    def list_stale(self, now: datetime, limit: int = 100) -> list[AgentRun]:
        result = self._table.query(
            IndexName="StatusLeaseIdx",
            KeyConditionExpression=(
                Key("status").eq(AgentRunStatus.RUNNING.value)
                & Key("lease_expires_at").lte(now.isoformat())
            ),
            Limit=limit,
        )
        return [_run(item) for item in result.get("Items", [])]


class DynamoAgentToolCallRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_tool_calls")

    def create(self, call: AgentToolCall) -> AgentToolCall:
        self._table.put_item(
            Item=_encode(asdict(call)),
            ConditionExpression="attribute_not_exists(run_id) AND attribute_not_exists(call_id)",
        )
        return call

    def list_for_run(self, run_id: str, limit: int = 100) -> list[AgentToolCall]:
        result = self._table.query(
            KeyConditionExpression=Key("run_id").eq(run_id),
            ScanIndexForward=True,
            Limit=limit,
        )
        return [_tool_call(item) for item in result.get("Items", [])]


class DynamoAgentBudgetLedgerRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_budget_ledger")

    def append(self, entry: AgentBudgetEntry) -> AgentBudgetEntry:
        self._table.put_item(
            Item=_encode(asdict(entry)),
            ConditionExpression="attribute_not_exists(session_id) AND attribute_not_exists(entry_id)",
        )
        return entry

    def list_for_session(
        self, session_id: str, limit: int = 100
    ) -> list[AgentBudgetEntry]:
        result = self._table.query(
            KeyConditionExpression=Key("session_id").eq(session_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        entries = [
            _budget(item)
            for item in result.get("Items", [])
            if not item["entry_id"].startswith("total#")
        ]
        return entries

    def reserve(self, session_id: str, resource: str, amount: int, limit: int) -> bool:
        if amount <= 0 or amount > limit:
            return False
        try:
            self._table.update_item(
                Key={"session_id": session_id, "entry_id": f"total#{resource}"},
                UpdateExpression="SET amount = if_not_exists(amount, :zero) + :amount",
                ConditionExpression="attribute_not_exists(amount) OR amount <= :maximum_before_spend",
                ExpressionAttributeValues={
                    ":zero": 0,
                    ":amount": amount,
                    ":maximum_before_spend": limit - amount,
                },
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True


class DynamoAgentEntityClaimRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_entity_claims")

    def claim(self, claim: AgentEntityClaim) -> AgentEntityClaim:
        self._table.put_item(Item=_encode(asdict(claim)))
        return claim

    def list_by_entity(
        self, entity_key: str, limit: int = 50
    ) -> list[AgentEntityClaim]:
        result = self._table.query(
            KeyConditionExpression=Key("entity_key").eq(entity_key), Limit=limit
        )
        return [_entity_claim(item) for item in result.get("Items", [])]

    def list_by_session(
        self, session_id: str, limit: int = 100
    ) -> list[AgentEntityClaim]:
        result = self._table.query(
            IndexName="SessionIdx",
            KeyConditionExpression=Key("session_id").eq(session_id),
            Limit=limit,
        )
        return [_entity_claim(item) for item in result.get("Items", [])]

    def release_session(self, session_id: str) -> int:
        claims = self.list_by_session(session_id, limit=100)
        for claim in claims:
            self._table.delete_item(
                Key={"entity_key": claim.entity_key, "session_id": session_id}
            )
        return len(claims)


class DynamoAgentVerificationRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_verifications")

    def create(self, verification: AgentVerification) -> AgentVerification:
        self._table.put_item(
            Item=_encode(asdict(verification)),
            ConditionExpression="attribute_not_exists(subject_id) AND attribute_not_exists(verification_id)",
        )
        return verification

    def get(self, subject_id: str, verification_id: str) -> AgentVerification | None:
        item = self._table.get_item(
            Key={"subject_id": subject_id, "verification_id": verification_id}
        ).get("Item")
        return _verification(item) if item else None

    def update(
        self, verification: AgentVerification, *, expected_status: str
    ) -> AgentVerification:
        self._table.put_item(
            Item=_encode(asdict(verification)),
            ConditionExpression="#status = :expected",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":expected": expected_status},
        )
        return verification

    def list_for_subject(self, subject_id: str) -> list[AgentVerification]:
        result = self._table.query(
            KeyConditionExpression=Key("subject_id").eq(subject_id),
            ScanIndexForward=False,
        )
        return [_verification(item) for item in result.get("Items", [])]


class DynamoAgentPackageRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_packages")

    def create(self, package: AgentPackage) -> AgentPackage:
        self._table.put_item(
            Item=_encode(asdict(package)),
            ConditionExpression="attribute_not_exists(package_id)",
        )
        return package

    def get(self, package_id: str) -> AgentPackage | None:
        item = self._table.get_item(Key={"package_id": package_id}).get("Item")
        return _package(item) if item else None

    def list_for_session(self, session_id: str, limit: int = 50) -> list[AgentPackage]:
        result = self._table.query(
            IndexName="SessionIdx",
            KeyConditionExpression=Key("session_id").eq(session_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_package(item) for item in result.get("Items", [])]

    def update(self, package: AgentPackage, expected_rev: int) -> AgentPackage:
        item = _encode(asdict(package))
        item["rev"] = expected_rev + 1
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="rev = :expected AND #status <> :sealed",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":expected": expected_rev,
                    ":sealed": "SEALED",
                },
            )
        except ClientError as error:
            _raise_if_conflict(error)
        return _package(item)


class DynamoAgentConfirmationRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_confirmations")

    def create(self, confirmation: AgentConfirmation) -> AgentConfirmation:
        self._table.put_item(
            Item=_encode(asdict(confirmation)),
            ConditionExpression="attribute_not_exists(session_id) AND attribute_not_exists(confirmation_id)",
        )
        return confirmation

    def list_for_session(
        self, session_id: str, limit: int = 100
    ) -> list[AgentConfirmation]:
        result = self._table.query(
            KeyConditionExpression=Key("session_id").eq(session_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_confirmation(item) for item in result.get("Items", [])]


class DynamoAgentPromptRepository:
    def __init__(self) -> None:
        dynamodb = get_dynamodb_resource()
        self._prompts = dynamodb.Table("agent_prompts")
        self._active = dynamodb.Table("agent_prompt_active")

    def create_version(self, prompt: AgentPrompt) -> AgentPrompt:
        self._prompts.put_item(
            Item=_encode(_named_item(asdict(prompt))),
            ConditionExpression="attribute_not_exists(prompt_name) AND attribute_not_exists(version)",
        )
        return prompt

    def get_version(self, name: str, version: int) -> AgentPrompt | None:
        item = self._prompts.get_item(
            Key={"prompt_name": name, "version": version}
        ).get("Item")
        return _prompt(item) if item else None

    def get_active(self, name: str) -> ActiveAgentPrompt | None:
        item = self._active.get_item(Key={"prompt_name": name}).get("Item")
        return _active_prompt(item) if item else None

    def activate(
        self, pointer: ActiveAgentPrompt, expected_version: int | None
    ) -> None:
        if self.get_version(pointer.name, pointer.version) is None:
            raise ValueError("prompt version does not exist")
        item = _encode(_named_item(asdict(pointer)))
        if expected_version is None:
            condition = "attribute_not_exists(prompt_name)"
            values = None
        else:
            condition = "version = :expected"
            values = {":expected": expected_version}
        kwargs: dict[str, Any] = {"Item": item, "ConditionExpression": condition}
        if values:
            kwargs["ExpressionAttributeValues"] = values
        try:
            self._active.put_item(**kwargs)
        except ClientError as error:
            _raise_if_conflict(error)


def _encode(item: dict[str, Any]) -> dict[str, Any]:
    return to_dynamodb(
        {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in item.items()
            if value is not None
        }
    )


def _raise_if_conflict(error: ClientError) -> None:
    if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
        raise AgentRecordConflictError(
            "agent record changed or already exists"
        ) from error
    raise error


def _decoded(item: dict[str, Any]) -> dict[str, Any]:
    return from_dynamodb(item)


def _iteration(item: dict[str, Any]) -> AgentIteration:
    row = _decoded(item)
    return AgentIteration(
        session_id=row["session_id"],
        number=int(row["number"]),
        status=AgentIterationStatus(row["status"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"])
        if row.get("finished_at")
        else None,
        run_ids=tuple(row.get("run_ids", [])),
        package_id=row.get("package_id"),
        decision=row.get("decision", {}),
    )


def _experiment(item: dict[str, Any]) -> AgentExperiment:
    row = _decoded(item)
    return AgentExperiment(
        session_id=row["session_id"],
        experiment_id=row["experiment_id"],
        iteration_number=int(row["iteration_number"]),
        kind=AgentExperimentKind(row["kind"]),
        status=AgentExperimentStatus(row["status"]),
        components=tuple(
            ComponentVersionReference(**reference)
            for reference in row.get("components", [])
        ),
        objective_id=row["objective_id"],
        objective_version=int(row["objective_version"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        baseline_components=tuple(
            ComponentVersionReference(**reference)
            for reference in row.get("baseline_components", [])
        ),
        snapshot_id=row.get("snapshot_id"),
        snapshot_sha256=row.get("snapshot_sha256"),
        completed_at=datetime.fromisoformat(row["completed_at"])
        if row.get("completed_at")
        else None,
        global_evaluation=row.get("global_evaluation", {}),
        error_code=row.get("error_code"),
    )


def _component_pins_hash(
    components: tuple[ComponentVersionReference, ...],
    baseline_components: tuple[ComponentVersionReference, ...],
) -> str:
    payload = {
        name: [
            {
                "component": item.component,
                "entity_id": item.entity_id,
                "version": item.version,
                "content_sha256": item.content_sha256,
            }
            for item in items
        ]
        for name, items in (
            ("candidate", components),
            ("baseline", baseline_components),
        )
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _experiment_item(experiment: AgentExperiment) -> dict[str, Any]:
    item = asdict(experiment)
    item["component_pins_sha256"] = _component_pins_hash(
        experiment.components, experiment.baseline_components
    )
    return item


def _run(item: dict[str, Any]) -> AgentRun:
    row = _decoded(item)
    return AgentRun(
        run_id=row["run_id"],
        session_id=row["session_id"],
        iteration_number=int(row["iteration_number"]),
        subagent=row["subagent"],
        status=AgentRunStatus(row["status"]),
        prompt_ref=row["prompt_ref"],
        created_at=datetime.fromisoformat(row["created_at"]),
        lease_expires_at=datetime.fromisoformat(row["lease_expires_at"])
        if row.get("lease_expires_at")
        else None,
        error_code=row.get("error_code"),
    )


def _tool_call(item: dict[str, Any]) -> AgentToolCall:
    row = _decoded(item)
    row["created_at"] = datetime.fromisoformat(row["created_at"])
    return AgentToolCall(**row)


def _budget(item: dict[str, Any]) -> AgentBudgetEntry:
    row = _decoded(item)
    row["created_at"] = datetime.fromisoformat(row["created_at"])
    return AgentBudgetEntry(**row)


def _entity_claim(item: dict[str, Any]) -> AgentEntityClaim:
    row = _decoded(item)
    for field in ("claimed_at", "heartbeat_at", "expires_at"):
        row[field] = datetime.fromisoformat(row[field])
    return AgentEntityClaim(**row)


def _hypothesis(item: dict[str, Any]) -> AgentHypothesis:
    row = _decoded(item)
    row["status"] = AgentHypothesisStatus(row["status"])
    for field in ("created_at", "updated_at"):
        row[field] = datetime.fromisoformat(row[field])
    return AgentHypothesis(**row)


def _verification(item: dict[str, Any]) -> AgentVerification:
    row = _decoded(item)
    if row.get("created_at"):
        row["created_at"] = datetime.fromisoformat(row["created_at"])
    return AgentVerification(**row)


def _package(item: dict[str, Any]) -> AgentPackage:
    row = _decoded(item)
    if row.get("created_at"):
        row["created_at"] = datetime.fromisoformat(row["created_at"])
    if row.get("sealed_at"):
        row["sealed_at"] = datetime.fromisoformat(row["sealed_at"])
    return AgentPackage(**row)


def _confirmation(item: dict[str, Any]) -> AgentConfirmation:
    row = _decoded(item)
    row["confirmed_at"] = datetime.fromisoformat(row["confirmed_at"])
    return AgentConfirmation(**row)


def _prompt(item: dict[str, Any]) -> AgentPrompt:
    row = _decoded(item)
    row["name"] = row.pop("prompt_name")
    row["created_at"] = datetime.fromisoformat(row["created_at"])
    return AgentPrompt(**row)


def _active_prompt(item: dict[str, Any]) -> ActiveAgentPrompt:
    row = _decoded(item)
    row["name"] = row.pop("prompt_name")
    row["activated_at"] = datetime.fromisoformat(row["activated_at"])
    return ActiveAgentPrompt(**row)


def _named_item(item: dict[str, Any]) -> dict[str, Any]:
    """Map the domain's ``name`` field to DynamoDB's ``prompt_name`` key."""
    return {
        "prompt_name" if key == "name" else key: value for key, value in item.items()
    }
