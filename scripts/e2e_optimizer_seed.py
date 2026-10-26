"""Seed optimizer sessions in every state so the UI and its E2E can be checked fast.

The ARIA optimizer takes minutes to reach a "blocked" or "failed" state for real, so
UI scenarios are seeded through the repositories the application itself uses and then
read back through nginx and the API like any other session.

    python scripts/e2e_optimizer_seed.py seed --owner-email e2e-channel_manager@aria.local \
        --state blocked_budget [--prefix e2e]
    python scripts/e2e_optimizer_seed.py cleanup --prefix e2e

`seed` prints one JSON line with the new session id. Rows are plain application data:
no customer rows, amounts or prompts.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# The seeder runs on the host next to the E2E runner, whose environment points at
# the containers; always talk to the published DynamoDB port with the repo defaults.
os.environ["DYNAMO_ENDPOINT"] = os.getenv(
    "E2E_DYNAMO_ENDPOINT",
    f"http://localhost:{os.getenv('LOCAL_DYNAMODB_PORT', '8002')}",
)
# `test` loads the repo defaults; DYNAMO_ENDPOINT above points it at the local stack.
os.environ["GENAI_ENVIRONMENT"] = "test"

import boto3  # noqa: E402
from boto3.dynamodb.conditions import Attr, Key  # noqa: E402

from src.application.ports.agent_budget_ledger_port import (
    AgentBudgetEntry,  # noqa: E402
)
from src.application.ports.agent_hypothesis_port import (  # noqa: E402
    AgentHypothesis,
    AgentHypothesisStatus,
)
from src.application.ports.agent_insight_port import (  # noqa: E402
    AgentInsight,
    AgentInsightKind,
    AgentInsightStatus,
)
from src.application.ports.agent_iteration_port import (  # noqa: E402
    AgentIteration,
    AgentIterationStatus,
)
from src.application.ports.agent_run_port import AgentRun, AgentRunStatus
from src.application.ports.agent_session_port import (  # noqa: E402
    AgentSession,
    AgentSessionStatus,
)
from src.domain.agents.event import (  # noqa: E402
    AgentEvent,
    AgentEventKind,
    AgentEventOutcome,
)
from src.domain.agents.experiment import (  # noqa: E402
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.domain.agents.finding import (  # noqa: E402
    AgentFinding,
    AgentFindingKind,
    OptimizerInsight,
    OptimizerInsightKind,
    OptimizerInsightStatus,
)
from src.domain.agents.optimization_run import (
    OptimizationRun,
    OptimizationRunStatus,
    rank_winners,
)
from src.infrastructure.agents.factories import (  # noqa: E402
    get_agent_budget_ledger_repository,
    get_agent_event_repository,
    get_agent_experiment_repository,
    get_agent_finding_repository,
    get_agent_hypothesis_repository,
    get_agent_insight_repository,
    get_agent_iteration_repository,
    get_agent_run_repository,
    get_agent_session_repository,
    get_optimization_run_repository,
    get_optimizer_insight_repository,
)

STATES = (
    "running",
    "stalled",
    "blocked_budget",
    "blocked_candidates",
    "blocked_context",
    "failing",
    "inconclusive",
    "completed",
    "parallel",
)
SESSION_TABLES = (
    ("agent_events", "seq"),
    ("agent_iterations", "number"),
    ("agent_insights", "insight_id"),
    ("agent_budget_ledger", "entry_id"),
)
LIMITS = {"tokens": 100_000, "usd_micros": 50_000_000, "seconds": 43_200}
PINS = {
    name: ComponentVersionReference(name, f"{name}-1", "1", "a" * 64)
    for name in ("model", "configuration", "library", "vector_store")
}


def _resource():
    return boto3.resource(
        "dynamodb",
        endpoint_url=os.environ["DYNAMO_ENDPOINT"],
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


def owner_id_for(email: str) -> str:
    table = _resource().Table("users")
    items = table.scan(FilterExpression=Attr("email").eq(email)).get("Items", [])
    if not items:
        raise SystemExit(f"No local user with email {email}")
    return str(items[0]["user_id"])


class _Seeder:
    def __init__(self, owner_id: str, session_id: str, state: str) -> None:
        self.owner_id = owner_id
        self.session_id = session_id
        self.state = state
        self.now = datetime.now(UTC)
        self.events: list[AgentEvent] = []
        self._clock = self.now - timedelta(minutes=30)

    def tick(self, seconds: int = 20) -> datetime:
        self._clock += timedelta(seconds=seconds)
        return self._clock

    def event(
        self,
        kind,
        outcome,
        summary,
        *,
        reason=None,
        refs=None,
        duration_ms=None,
        stream=None,
    ) -> None:
        self.events.append(
            get_agent_event_repository().append(
                AgentEvent(
                    session_id=stream or self.session_id,
                    seq=0,
                    event_id=str(uuid.uuid4()),
                    occurred_at=self.tick(),
                    kind=kind,
                    outcome=outcome,
                    summary=summary,
                    reason_code=reason,
                    refs={key: str(value) for key, value in (refs or {}).items()},
                    duration_ms=duration_ms,
                )
            )
        )

    def iteration(self, number, status, run_ids=None, **decision) -> None:
        started = self.tick()
        get_agent_iteration_repository().create(
            AgentIteration(
                session_id=self.session_id,
                number=number,
                status=status,
                started_at=started,
                finished_at=None
                if status == AgentIterationStatus.RUNNING
                else self.tick(),
                run_ids=run_ids or (str(uuid.uuid4()),),
                decision=dict(decision),
            )
        )

    def hypothesis(
        self,
        statement,
        status,
        *,
        insight_id=None,
        area="model",
        conclusion=None,
        depends_on=(),
        priority=1,
    ) -> str:
        hypothesis_id = str(uuid.uuid4())
        get_agent_hypothesis_repository().create(
            AgentHypothesis(
                session_id=self.session_id,
                hypothesis_id=hypothesis_id,
                statement=statement,
                scope={"area": area},
                priority=priority,
                status=status,
                created_at=self.tick(),
                updated_at=self.tick(),
                source_insight_id=insight_id,
                insight_ids=(insight_id,) if insight_id else (),
                depends_on=tuple(depends_on),
                conclusion=conclusion or _conclusion(status),
            )
        )
        return hypothesis_id

    def spend(self, tokens, usd_micros, seconds) -> None:
        for resource, amount in (
            ("tokens", tokens),
            ("usd_micros", usd_micros),
            ("seconds", seconds),
        ):
            get_agent_budget_ledger_repository().append(
                AgentBudgetEntry(
                    session_id=self.session_id,
                    entry_id=str(uuid.uuid4()),
                    entry_type="SPEND",
                    resource=resource,
                    amount=amount,
                    actor="agent",
                    reason="seeded iteration",
                    created_at=self.tick(),
                )
            )

    def experiment(
        self,
        number,
        status,
        *,
        error=None,
        evaluation=None,
        candidate_id=None,
        changed=("model",),
    ) -> str:
        experiment_id = str(uuid.uuid4())
        candidate = dict(PINS)
        for component in changed:
            candidate[component] = ComponentVersionReference(
                component, f"{component}-2", "2", "b" * 64
            )
        get_agent_experiment_repository().create(
            AgentExperiment(
                session_id=self.session_id,
                experiment_id=experiment_id,
                iteration_number=number,
                kind=(
                    AgentExperimentKind.COMBINATION
                    if len(changed) > 1
                    else AgentExperimentKind.ISOLATED
                ),
                status=status,
                components=tuple(candidate.values()),
                baseline_components=tuple(PINS.values()),
                objective_id="seed-objective",
                objective_version=1,
                created_at=self.tick(),
                completed_at=None
                if status == AgentExperimentStatus.RUNNING
                else self.tick(),
                global_evaluation=evaluation or {},
                error_code=error,
                candidate_id=candidate_id,
            )
        )
        stream = f"{self.session_id}#exp#{experiment_id}"
        self.event(
            AgentEventKind.EXPERIMENT,
            AgentEventOutcome.STARTED,
            "Experimento iniciado",
            refs={"iteration": number, "experiment_id": experiment_id},
            stream=stream,
        )
        if status != AgentExperimentStatus.RUNNING:
            self.event(
                AgentEventKind.EXPERIMENT,
                AgentEventOutcome.SUCCEEDED
                if status == AgentExperimentStatus.SUCCEEDED
                else AgentEventOutcome.FAILED,
                "Experimento cumplió el objetivo global"
                if status == AgentExperimentStatus.SUCCEEDED
                else "Experimento falló",
                reason=error,
                refs={"iteration": number, "experiment_id": experiment_id},
                stream=stream,
            )
        return experiment_id


def _conclusion(status, recall=0.71, baseline=0.6) -> dict:
    if status == AgentHypothesisStatus.ACTIVE:
        return {}
    verdict = status.value
    return {
        "verdict": verdict,
        "summary": {
            "VALIDATED": f"Mejora el recall en {(recall - baseline) * 100:.1f} pts sin bajar del piso de precisión.",
            "REFUTED": "No cumple el objetivo: se descarta.",
        }.get(verdict, "La evidencia no alcanza para concluir."),
        "evidence": {"recall": recall, "precision": 0.94, "baseline_recall": baseline}
        if verdict == "VALIDATED"
        else {},
        "decision": {"VALIDATED": "keep", "REFUTED": "discard"}.get(verdict, "retry"),
        "recommendation": {
            "VALIDATED": "Candidato a promover o a combinar con otros ganadores.",
            "REFUTED": "Descartar este cambio.",
        }.get(verdict, "Repetir con más evidencia o con otro enfoque."),
    }


def _evaluation(recall: float) -> dict:
    """Same shape the experiment evaluator publishes."""
    return {
        "status": "PASSED",
        "sample": {"partition": "final", "eligible_count": 120},
        "metrics": {
            "candidate": {"precision": 0.94, "recall": recall, "eligible_count": 120},
            "baseline": {"precision": 0.93, "recall": 0.6},
        },
    }


def _seed_root(session_id: str, now, areas, status, insight_ids=()) -> None:
    experiments = get_agent_experiment_repository().list_for_session(session_id, 200)
    winners = rank_winners(
        [(item.candidate_id, item) for item in experiments if item.candidate_id]
    )
    best = next(
        (
            item
            for item in experiments
            if winners and item.experiment_id == winners[0].experiment_id
        ),
        None,
    )
    distinct = {item.component for item in winners if "+" not in item.component}
    combined = any("+" in item.component for item in winners)
    strategy = (
        {
            "action": "explore",
            "rationale": "Aún no hay un candidato que mejore el objetivo.",
        }
        if not winners
        else {
            "action": "combine",
            "rationale": "Hay ganadores en componentes distintos; se medirán juntos.",
        }
        if len(distinct) >= 2 and not combined
        else {
            "action": "promote",
            "rationale": f"El mejor candidato mejora el recall en {winners[0].recall_delta * 100:.1f} pts sobre la línea base.",
            "winner": winners[0].candidate_id,
        }
    )
    get_optimization_run_repository().create_once(
        OptimizationRun(
            run_id=session_id,
            status=status,
            created_at=now - timedelta(minutes=31),
            updated_at=now,
            objective_id="seed-objective",
            objective_version=1,
            baseline_components=tuple(PINS.values()),
            budget_limits=dict(LIMITS),
            optimizer_settings={
                "max_parallel_experiments": 3,
                "max_concurrent_runs": 6,
                "iterations_without_improvement": 3,
                "precision_floor": 0.9,
            },
            scope_areas=tuple(areas),
            insight_ids=tuple(insight_ids),
            winners=winners,
            winning_components=best.components if best else (),
            strategy=strategy,
            events_stream=session_id,
        )
    )


def _seed_parallel(owner_id: str, session_id: str) -> str:
    """Three independent candidates running at once, each with a live run lease."""
    seeder = _Seeder(owner_id, session_id, "parallel")
    now = seeder.now
    areas = ("model", "configuration", "library")
    for number, area in enumerate(areas, start=1):
        hypothesis_id = seeder.hypothesis(
            f"Evaluar si el área {area} puede mejorar el recall sin incumplir el piso de precisión.",
            AgentHypothesisStatus.ACTIVE,
            area=area,
        )
        run_id = str(uuid.uuid4())
        get_agent_run_repository().create(
            AgentRun(
                run_id=run_id,
                session_id=session_id,
                iteration_number=number,
                subagent={"model": "xgboost"}.get(area, area),
                status=AgentRunStatus.RUNNING,
                prompt_ref={},
                created_at=now,
                lease_expires_at=now + timedelta(minutes=10),
            )
        )
        seeder.iteration(
            number,
            AgentIterationStatus.RUNNING,
            run_ids=(run_id,),
            hypothesis_id=hypothesis_id,
            action="running",
        )
        seeder.event(
            AgentEventKind.ITERATION,
            AgentEventOutcome.STARTED,
            f"Iteración {number} iniciada",
            refs={"iteration": number, "run_id": run_id},
        )
    seeder.spend(3, 3, 3)
    get_agent_session_repository().create(
        AgentSession(
            session_id=session_id,
            mode="optimization",
            status=AgentSessionStatus.ACTIVE,
            owner_id=owner_id,
            created_at=now - timedelta(minutes=31),
            updated_at=now,
            scope={"areas": list(areas)},
            budget_limits=dict(LIMITS),
            baseline_components=tuple(PINS.values()),
        )
    )
    _seed_root(session_id, now, areas, OptimizationRunStatus.RUNNING)
    return session_id


def seed(owner_id: str, state: str, prefix: str) -> str:
    session_id = f"{prefix}-{state.replace('_', '-')}-{uuid.uuid4().hex[:8]}"
    if state == "parallel":
        return _seed_parallel(owner_id, session_id)
    seeder = _Seeder(owner_id, session_id, state)
    now = seeder.now
    status = {
        "running": AgentSessionStatus.ACTIVE,
        "stalled": AgentSessionStatus.ACTIVE,
        "failing": AgentSessionStatus.ACTIVE,
        "blocked_budget": AgentSessionStatus.WAITING_USER,
        "blocked_candidates": AgentSessionStatus.WAITING_USER,
        "blocked_context": AgentSessionStatus.WAITING_USER,
        "inconclusive": AgentSessionStatus.STOPPED,
        "completed": AgentSessionStatus.COMPLETED,
    }[state]
    block = {
        "blocked_budget": "BUDGET_EXHAUSTED",
        "blocked_candidates": "CANDIDATE_LIMIT_REACHED",
        "blocked_context": "CONTEXT_MISSING",
    }.get(state)

    refs = {"iteration": 1}
    seeder.event(
        AgentEventKind.ITERATION,
        AgentEventOutcome.STARTED,
        "Iteración 1 iniciada",
        refs=refs,
    )
    insight_id = None
    if state in {"completed", "blocked_context"}:
        insight_id = str(uuid.uuid4())
        now_i = seeder.tick()
        get_agent_insight_repository().create(
            AgentInsight(
                session_id=session_id,
                insight_id=insight_id,
                kind=AgentInsightKind.DIRECTIVE,
                statement="Priorizar los falsos positivos de Digital en la noche",
                scope={},
                status=AgentInsightStatus.ACTIVE,
                proposed_by="user",
                author_id=owner_id,
                source_message_id=None,
                created_at=now_i,
                updated_at=now_i,
            )
        )
    first = seeder.hypothesis(
        "Evaluar si el área model puede mejorar el recall sin incumplir el piso de precisión.",
        {
            "completed": AgentHypothesisStatus.VALIDATED,
            "inconclusive": AgentHypothesisStatus.REFUTED,
            "blocked_context": AgentHypothesisStatus.NONCONCLUSIVE,
            "blocked_budget": AgentHypothesisStatus.VALIDATED,
            "blocked_candidates": AgentHypothesisStatus.REFUTED,
        }.get(state, AgentHypothesisStatus.ACTIVE),
        insight_id=insight_id,
    )
    hypothesis_refs = {**refs, "hypothesis_id": first}
    seeder.event(
        AgentEventKind.HYPOTHESIS,
        AgentEventOutcome.STARTED,
        "Hipótesis en prueba",
        refs=hypothesis_refs,
    )
    seeder.event(
        AgentEventKind.SPECIALIST,
        AgentEventOutcome.STARTED,
        "Especialista xgboost en ejecución",
        refs={**refs, "specialist": "xgboost"},
    )

    experiment_id = None
    if state in {"completed", "blocked_budget"}:
        experiment_id = seeder.experiment(
            1,
            AgentExperimentStatus.SUCCEEDED,
            evaluation=_evaluation(0.71),
            candidate_id=first,
        )
    elif state == "failing":
        experiment_id = seeder.experiment(
            1,
            AgentExperimentStatus.FAILED,
            error="PIPELINE_REPLAY_WORKFLOW_FAILED",
            candidate_id=first,
        )

    if state == "failing":
        seeder.event(
            AgentEventKind.SPECIALIST,
            AgentEventOutcome.FAILED,
            "Falló el entrenamiento",
            reason="MODEL_TRAINING_FAILED",
            refs={**refs, "specialist": "xgboost"},
            duration_ms=42_000,
        )
        seeder.iteration(
            1,
            AgentIterationStatus.FAILED,
            action="continue",
            failure_code="MODEL_TRAINING_FAILED",
        )
    elif state in {"running", "stalled"}:
        seeder.iteration(1, AgentIterationStatus.RUNNING)
    else:
        seeder.event(
            AgentEventKind.SPECIALIST,
            AgentEventOutcome.SUCCEEDED,
            "Especialista xgboost terminó",
            refs={**refs, "specialist": "xgboost"},
            duration_ms=18_500,
        )
        seeder.event(
            AgentEventKind.VERIFICATION,
            AgentEventOutcome.SUCCEEDED,
            "Verificación aprobada",
            refs={**refs, "verification_id": str(uuid.uuid4())},
        )
        if experiment_id:
            seeder.event(
                AgentEventKind.EXPERIMENT,
                AgentEventOutcome.SUCCEEDED,
                "Experimento cumplió el objetivo global",
                refs={**refs, "experiment_id": experiment_id, "hypothesis_id": first},
            )
        seeder.event(
            AgentEventKind.ITERATION,
            AgentEventOutcome.SUCCEEDED,
            "Iteración 1 terminó",
            refs=refs,
            duration_ms=61_000,
        )
        seeder.iteration(
            1, AgentIterationStatus.SUCCEEDED, action="continue", score=0.71
        )

    if state == "completed":
        second = seeder.hypothesis(
            "Evaluar si el área configuration puede mejorar el recall sin incumplir el piso de precisión.",
            AgentHypothesisStatus.VALIDATED,
            area="configuration",
            conclusion=_conclusion(AgentHypothesisStatus.VALIDATED, recall=0.68),
        )
        seeder.experiment(
            2,
            AgentExperimentStatus.SUCCEEDED,
            evaluation=_evaluation(0.68),
            candidate_id=second,
            changed=("configuration",),
        )
        combination = seeder.hypothesis(
            "Combinar los ganadores (configuration, model) y medirlos juntos contra la línea base.",
            AgentHypothesisStatus.VALIDATED,
            area="combination",
            depends_on=(first, second),
            priority=200,
            conclusion=_conclusion(AgentHypothesisStatus.VALIDATED, recall=0.76),
        )
        seeder.experiment(
            3,
            AgentExperimentStatus.SUCCEEDED,
            evaluation=_evaluation(0.76),
            candidate_id=combination,
            changed=("model", "configuration"),
        )
        seeder.event(
            AgentEventKind.PRODUCTION_CHANGE,
            AgentEventOutcome.SUCCEEDED,
            "Despliegue gradual avanzado",
            refs={
                "release_id": str(uuid.uuid4()),
                "audit_correlation_id": str(uuid.uuid4()),
            },
        )
        get_agent_finding_repository().create_once(
            AgentFinding(
                session_id=session_id,
                finding_id=f"{experiment_id}:candidate",
                kind=AgentFindingKind.DIAGNOSTIC,
                dimension="pipeline",
                dimension_value="candidate",
                sample_count=120,
                metrics={"precision": 0.94, "recall": 0.71},
                source="global_evaluation",
                created_at=seeder.tick(),
            )
        )
        get_agent_finding_repository().create_once(
            AgentFinding(
                session_id=session_id,
                finding_id=f"{experiment_id}:baseline",
                kind=AgentFindingKind.DIAGNOSTIC,
                dimension="pipeline",
                dimension_value="baseline",
                sample_count=120,
                metrics={"precision": 0.93, "recall": 0.6},
                source="global_evaluation",
                created_at=seeder.tick(),
            )
        )
        try:
            get_optimizer_insight_repository().create(
                OptimizerInsight(
                    insight_id=f"seed-{uuid.uuid4().hex[:8]}",
                    statement="El área xgboost mejora el recall sin perder precisión",
                    kind=OptimizerInsightKind.PATTERN,
                    scope_key="area:model",
                    status=OptimizerInsightStatus.SUPPORTED,
                    sample_count=120,
                    created_at=now,
                    last_evaluated_at=now,
                    review_after=now + timedelta(days=30),
                    evidence_summary={
                        "candidate_recall": 0.71,
                        "baseline_recall": 0.6,
                    },
                    origin_session_id=session_id,
                )
            )
        except Exception:  # noqa: BLE001 - memory is a nice-to-have for the scenario
            pass

    if block:
        seeder.event(
            AgentEventKind.BLOCKED,
            AgentEventOutcome.BLOCKED,
            {
                "BUDGET_EXHAUSTED": "Presupuesto agotado",
                "CANDIDATE_LIMIT_REACHED": "Límite de propuestas alcanzado",
                "CONTEXT_MISSING": "Falta contexto",
            }[block],
            reason=block,
            refs=refs,
        )
    spent = {
        "blocked_budget": (50_000, 25_000_000, 1_000),
    }.get(state, (12_000, 2_400_000, 900))
    seeder.spend(*spent)

    lease_owner = lease_expires = None
    if state == "running":
        lease_owner, lease_expires = "seed-worker", now + timedelta(seconds=75)
    elif state == "stalled":
        lease_owner, lease_expires = "seed-worker", now - timedelta(minutes=5)
    limits = (
        # Below the global ceilings, so the Channel Manager can still grant more.
        {"tokens": spent[0], "usd_micros": spent[1], "seconds": 43_200}
        if state == "blocked_budget"
        else LIMITS
    )
    get_agent_session_repository().create(
        AgentSession(
            session_id=session_id,
            mode="optimization",
            status=status,
            owner_id=owner_id,
            created_at=now - timedelta(minutes=31),
            updated_at=now,
            scope={"areas": ["model"]},
            budget_limits=limits,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires,
            block=({"code": block, "since": now.isoformat()} if block else {}),
        )
    )
    _seed_root(
        session_id,
        now,
        ("model", "configuration") if state == "completed" else ("model",),
        {
            "completed": OptimizationRunStatus.COMPLETED,
            "inconclusive": OptimizationRunStatus.STOPPED,
        }.get(
            state,
            OptimizationRunStatus.WAITING_USER
            if block
            else OptimizationRunStatus.RUNNING,
        ),
        (insight_id,) if insight_id else (),
    )
    return session_id


def cleanup(prefix: str) -> int:
    resource = _resource()
    sessions = resource.Table("agent_sessions")
    removed = 0
    for item in sessions.scan(
        FilterExpression=Attr("session_id").begins_with(f"{prefix}-")
    ).get("Items", []):
        session_id = item["session_id"]
        for table_name, sort_key in SESSION_TABLES:
            table = resource.Table(table_name)
            rows = table.query(
                KeyConditionExpression=Key("session_id").eq(session_id)
            ).get("Items", [])
            for row in rows:
                table.delete_item(
                    Key={"session_id": session_id, sort_key: row[sort_key]}
                )
        runs = resource.Table("optimization_runs")
        for row in runs.query(KeyConditionExpression=Key("run_id").eq(session_id)).get(
            "Items", []
        ):
            runs.delete_item(Key={"run_id": session_id, "node": row["node"]})
        sessions.delete_item(Key={"session_id": session_id})
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seed_parser = sub.add_parser("seed")
    seed_parser.add_argument("--owner-email")
    seed_parser.add_argument("--owner-id")
    seed_parser.add_argument("--state", choices=STATES, required=True)
    seed_parser.add_argument("--prefix", default="e2e")
    clean_parser = sub.add_parser("cleanup")
    clean_parser.add_argument("--prefix", default="e2e")
    args = parser.parse_args()
    if args.command == "cleanup":
        print(json.dumps({"removed": cleanup(args.prefix)}))
        return 0
    owner = args.owner_id or (
        owner_id_for(args.owner_email) if args.owner_email else None
    )
    if not owner:
        parser.error("--owner-id or --owner-email is required")
    print(
        json.dumps(
            {"session_id": seed(owner, args.state, args.prefix), "state": args.state}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
