"""Force the ARIA Grafana alert rules locally (docs/OBSERVABILITY_RUNBOOK.md).

Emits telemetry through the real monitoring adapter (`get_monitoring()`), so
it exercises the same instruments the app uses and goes app -> OTLP ->
Collector -> Prometheus/Tempo/Loki, exactly like production traffic.

    make observability-up
    python deploy/local/docker/observability/force_alerts.py <scenario> [--minutes N]

(defaults GENAI_ENVIRONMENT=local, API_V0_STR=/api/v0 and
OTEL_ENDPOINT=http://localhost:4317 unless already set in the environment).

Scenarios: demo, workflow-failing, sla-at-risk, dead-mans-switch, llm-down,
llm-slow, research-degraded, analyst-queue-stuck, no-capacity, rollup-drift.
Local tooling only: never imported by the app.
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))
os.chdir(_REPO_ROOT)  # Config reads ./config/$GENAI_ENVIRONMENT/config.cfg
os.environ.setdefault("GENAI_ENVIRONMENT", "local")
os.environ.setdefault("API_V0_STR", "/api/v0")
os.environ.setdefault("OTEL_ENDPOINT", "http://localhost:4317")

from src.application.ports.monitoring_port import (  # noqa: E402
    WORKFLOW_TOTAL_STEP,
    MonitoringPort,
    OperationalStateSnapshot,
    ResearchCallOutcome,
)
from src.infrastructure.monitoring.opentelemetry import (  # noqa: E402
    get_monitoring,
)

TICK_SECONDS = 15
logger = logging.getLogger("aria.force_alerts")

_HEALTHY_STATE = OperationalStateSnapshot(
    agent_enabled=False,
    within_operating_hours=True,
    analyst_queue_depth=0,
    analyst_queue_oldest_age_seconds=0.0,
    analysts_available=3,
    voicebot_slots_available=2,
)


def _state(**changes) -> OperationalStateSnapshot:
    return OperationalStateSnapshot(**{**_HEALTHY_STATE.__dict__, **changes})


def _llm_call(m: MonitoringPort, fail: bool = False, seconds: float = 0.2) -> None:
    try:
        with m.start(
            "forced_llm_call",
            "llm",
            metadata={
                "operation_name": "forced_llm_call",
                "provider": "azure_openai",
                "model": "forced-model",
            },
        ) as span:
            logger.info("forced llm call (fail=%s)", fail)
            time.sleep(seconds)
            if fail:
                raise ConnectionError("forced LLM outage")
            span.write_operation_metas({"input_tokens": 800, "output_tokens": 120})
    except ConnectionError:
        logger.warning("forced llm call failed")


def tick(scenario: str, m: MonitoringPort) -> None:
    if scenario == "demo":
        for _ in range(3):
            _llm_call(m, fail=random.random() < 0.1, seconds=random.uniform(0.1, 1.5))
        m.record_workflow_duration("classification", "SUCCEEDED", random.uniform(2, 8))
        m.record_workflow_duration(
            WORKFLOW_TOTAL_STEP, random.choice(["CLOSED", "ESCALATED"]), random.uniform(30, 200)
        )
        m.record_research_call("vector_store", ResearchCallOutcome.OK)
        m.record_rollup_drift("alert", "day", 0)
        m.record_operational_state(_state(agent_enabled=True, analyst_queue_depth=2,
                                          analyst_queue_oldest_age_seconds=120.0))
    elif scenario == "workflow-failing":
        m.record_workflow_duration(WORKFLOW_TOTAL_STEP, "FAILED", 5.0)
        m.record_workflow_duration(WORKFLOW_TOTAL_STEP, "CLOSED", 60.0)
    elif scenario == "sla-at-risk":
        m.record_workflow_duration(WORKFLOW_TOTAL_STEP, "CLOSED", 420.0)
    elif scenario == "dead-mans-switch":
        # Agent ON, nothing processed.
        m.record_operational_state(_state(agent_enabled=True))
    elif scenario == "llm-down":
        for _ in range(3):
            _llm_call(m, fail=True)
    elif scenario == "llm-slow":
        threads = [threading.Thread(target=_llm_call, args=(m, False, 31.0)) for _ in range(2)]
        for t in threads:
            t.start()
    elif scenario == "research-degraded":
        m.record_research_call("vector_store", ResearchCallOutcome.TIMEOUT)
        m.record_research_call("vector_store", ResearchCallOutcome.FAILED)
        m.record_research_call("vector_store", ResearchCallOutcome.OK)
    elif scenario == "analyst-queue-stuck":
        m.record_operational_state(
            _state(analyst_queue_depth=3, analyst_queue_oldest_age_seconds=1200.0)
        )
    elif scenario == "no-capacity":
        m.record_operational_state(_state(analysts_available=0))
    elif scenario == "rollup-drift":
        m.record_rollup_drift("alert", "day", 3)
    else:
        raise SystemExit(f"unknown scenario: {scenario}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario")
    parser.add_argument("--minutes", type=float, default=12.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    monitoring = get_monitoring()
    deadline = time.monotonic() + args.minutes * 60
    while time.monotonic() < deadline:
        tick(args.scenario, monitoring)
        time.sleep(TICK_SECONDS)
    print("done; telemetry is flushed at exit")


if __name__ == "__main__":
    main()
