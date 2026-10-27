"""Compare the fixed and LLM history planners on the same CSV batch.

Creates two inactive configuration lineages from a base configuration that
differ only in ``history_pandas.planner`` (history analysis switched on for
the Detector and Clasificación), runs the same uploaded dataset through both
as test runs, and reports per planner: inconclusive rate, accuracy against
the dataset's marcación, latency, tokens per alert and the history planner's
own trace (planning latency and tokens). Every row of the dataset is
dispatched in both runs, so the two planners see exactly the same alerts.

    python scripts/compare_history_planners.py --dataset-name <uploaded CSV> \
        [--configuration-id <id> --version <n>] [--output report.json]

Credentials come from E2E_MANAGER_EMAIL / E2E_MANAGER_PASSWORD (or flags).
Only aggregates are printed; no alert rows or prompts are read back.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

OPENER = build_opener(ProxyHandler({}))
PLANNERS = ("heuristic", "llm")
HISTORY_STEPS = ("detector", "classification")
TOOL_STEPS = ("detector", "detector_adversarial", "classification", "adversarial")


class Api:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/") + "/api/v0"
        self.token = ""

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with OPENER.open(request, timeout=60) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")[:500]
            raise SystemExit(f"{method} {path}: HTTP {error.code} {detail}") from error
        return json.loads(raw) if raw else None


def planner_variant(base: dict[str, Any], planner: str, name: str) -> dict[str, Any]:
    segments = copy.deepcopy(base["segments"])
    for segment in segments.values():
        agent = segment.get("agent") or {}
        for step in TOOL_STEPS:
            tools = agent.get(step)
            if not tools:
                continue
            history = tools.setdefault("delegated_research", {}).setdefault(
                "history_pandas", {}
            )
            history["planner"] = planner
            if step in HISTORY_STEPS:
                history["enabled"] = True
    return {
        "name": name,
        "description": f"Comparación del planner de historial: {planner}.",
        "general": base["general"],
        "infra": base["infra"],
        "test": base["test"],
        "segments": segments,
    }


def final_output(steps: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    attempts = [step for step in steps if step["step_name"] == name and step["output"]]
    return max(attempts, key=lambda step: step["attempt"])["output"] if attempts else None


def summarize(api: Api, run_id: str) -> dict[str, Any]:
    run = api.call("GET", f"/test-runs/{run_id}")
    total = run["total"] or 0
    inconclusive = decided_early = 0
    history_runs: list[dict[str, Any]] = []
    for case in run["cases"]:
        detail = api.call(
            "GET", f"/test-runs/{run_id}/cases/{case['workflow_execution_id']}"
        )
        steps = detail["steps"]
        decision = final_output(steps, "classification") or final_output(
            steps, "detector"
        )
        if decision is None:
            decided_early += 1
        elif decision.get("is_fraud") == "unknown":
            inconclusive += 1
        for step in HISTORY_STEPS:
            output = final_output(steps, step) or {}
            for item in output.get("research_delegations") or []:
                if item.get("source") == "history_pandas":
                    history_runs.append(item)
    executed = [item for item in history_runs if item.get("status") == "executed"]
    plans = [item["trace"][0] for item in executed if item.get("trace")]
    planning_ms = [plan["planning_ms"] for plan in plans if "planning_ms" in plan]
    planner_tokens = [
        (plan.get("planner_input_tokens") or 0) + (plan.get("planner_output_tokens") or 0)
        for plan in plans
    ]
    ground_truth = run.get("ground_truth_metrics") or {}
    matrix = ground_truth.get("confusion_matrix") or {}
    correct = sum(row.get(label, 0) for label, row in matrix.items())
    durations = run.get("total_duration_stats") or {}
    return {
        "test_run_id": run_id,
        "status": run["status"],
        "alerts": total,
        "failed": run["failed"],
        "inconclusive_rate": round(inconclusive / total, 4) if total else None,
        "decided_before_agent": decided_early,
        "accuracy_vs_marcacion": (
            round(correct / ground_truth["total"], 4) if ground_truth.get("total") else None
        ),
        "macro_f1": ground_truth.get("macro_f1"),
        "avg_seconds_per_alert": durations.get("avg_seconds"),
        "p95_seconds_per_alert": durations.get("p95_seconds"),
        "tokens_per_alert": (
            round((run["input_tokens"] + run["output_tokens"]) / total, 1) if total else None
        ),
        "history_analyses": len(history_runs),
        "history_failed": len(history_runs) - len(executed),
        "history_findings_per_analysis": (
            round(
                statistics.mean(len(item.get("findings") or []) for item in executed), 2
            )
            if executed
            else None
        ),
        "planner_seen": sorted({plan.get("planner", "?") for plan in plans}),
        "planning_ms_avg": round(statistics.mean(planning_ms), 1) if planning_ms else None,
        "planner_tokens_avg": (
            round(statistics.mean(planner_tokens), 1) if planner_tokens else None
        ),
    }


def wait(api: Api, run_ids: dict[str, str], timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    pending = dict(run_ids)
    while pending:
        if time.monotonic() > deadline:
            raise SystemExit(f"Timeout esperando las corridas: {sorted(pending)}")
        for planner, run_id in list(pending.items()):
            status = api.call("GET", f"/test-runs/{run_id}")["status"]
            if status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                print(f"{planner}: {status}", file=sys.stderr)
                pending.pop(planner)
        time.sleep(5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://localhost"))
    parser.add_argument("--email", default=os.getenv("E2E_MANAGER_EMAIL"))
    parser.add_argument("--password", default=os.getenv("E2E_MANAGER_PASSWORD"))
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--configuration-id", help="Base lineage (default: active).")
    parser.add_argument("--version", type=int, help="Base version (default: latest).")
    parser.add_argument("--timeout", type=int, default=3600, help="Seconds for both runs.")
    parser.add_argument("--output", help="Write the JSON report here as well.")
    args = parser.parse_args()
    if not args.email or not args.password:
        raise SystemExit("Define E2E_MANAGER_EMAIL/E2E_MANAGER_PASSWORD o --email/--password.")

    api = Api(args.base_url)
    api.token = api.call(
        "POST", "/auth/login", {"email": args.email, "password": args.password}
    )["access_token"]
    if args.configuration_id:
        suffix = f"/versions/{args.version}" if args.version else ""
        base = api.call("GET", f"/configurations/{args.configuration_id}{suffix}")
        if isinstance(base, list):
            base = max(base, key=lambda item: item["version"])
    else:
        base = api.call("GET", "/configurations/active")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_ids: dict[str, str] = {}
    configurations: dict[str, dict[str, Any]] = {}
    for planner in PLANNERS:
        created = api.call(
            "POST",
            "/configurations",
            planner_variant(base, planner, f"Planner historial {planner} {stamp}"),
        )
        configurations[planner] = {
            "configuration_id": created["configuration_id"],
            "version": created["version"],
        }
        started = api.call(
            "POST",
            "/test-runs",
            {
                "name": f"Planner historial {planner} {stamp}",
                "dataset_name": args.dataset_name,
                "config": {"configuration_ref": configurations[planner]},
            },
        )
        run_ids[planner] = started["test_run_id"]
        print(
            f"{planner}: corrida {started['test_run_id']} "
            f"({started['dispatched_count']} alertas)",
            file=sys.stderr,
        )

    wait(api, run_ids, args.timeout)
    report = {
        "dataset_name": args.dataset_name,
        "base_configuration": {
            "configuration_id": base["configuration_id"],
            "version": base["version"],
        },
        "configurations": configurations,
        "planners": {planner: summarize(api, run_ids[planner]) for planner in PLANNERS},
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
