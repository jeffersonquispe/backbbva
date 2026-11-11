"""E13: ARIA workflow traces in Arize Phoenix, through the real local stack.

Runs under the scripted-LLM runner (``scripts/e2e_alert_processing_local.py``
with ``E2E_ALERT_SCRIPT=scripts/e2e_phoenix.py``), like E07: only the model
provider is replaced; API (through nginx), Celery workers, DynamoDB, the OTLP
Collector, Phoenix and PostgreSQL are the real services.

Checks, for one real alert workflow:
  1. Phoenix holds a trace whose id is the workflow_execution_id (128 bits).
  2. Every persisted step execution (any attempt) is a span with the same
     ``aria.workflow.step_id`` / ``aria.workflow.step`` / ``aria.workflow.attempt``.
  3. LLM and tool calls are descendants of a step span, once each, with a unique
     ``aria.run_id``.
  4. No customer id, transaction/device id, counterparty or exact amount, and no
     prompt/completion content, reaches a span (content capture is off by default).
  5. The same trace is in Tempo: the Collector still fans out to the other backends.
  6. After restarting PostgreSQL and Phoenix the trace is still there, unchanged.
  7. With Phoenix stopped a new workflow still completes and reaches Tempo.

Not covered here:
  * Tool spans end to end. The scripted LLM always answers ``scale_to_analyst``
    and never calls a tool, so the workflow does not reach ``classification``;
    the tool-span assertion is applied only when it does. Tool spans are covered
    by ``test_classify_alert.py`` / ``test_adversarial_review_alert.py`` (one
    ``tool.<name>`` span per call, no content) and were seen in real Phoenix
    traces from the agent path (``tool.vector_store``).
  * Celery retry of a step across processes (unit tests) and the
    ``aria.workflow.id`` correlation of traces that start after the workflow
    (PENDIENTES.md §13).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_alert_processing as e07  # noqa: E402  (shared API client and event)

E2EFailure = e07.E2EFailure
require = e07.require

PHOENIX_URL = os.getenv("E2E_PHOENIX_URL", "http://localhost:6006").rstrip("/")
GRAFANA_URL = os.getenv("E2E_GRAFANA_URL", "http://localhost:3000").rstrip("/")
GRAFANA_AUTH = (
    os.getenv("E2E_GRAFANA_USER", "admin"),
    os.getenv("E2E_GRAFANA_PASSWORD", "admin"),
)
PHOENIX_CONTAINER = os.getenv("E2E_PHOENIX_CONTAINER", "aria-phoenix")
PHOENIX_DB_CONTAINER = os.getenv("E2E_PHOENIX_DB_CONTAINER", "aria-phoenix-db")
API_CONTAINER = os.getenv("E2E_API_CONTAINER", "aria-api")
DYNAMODB_URL = f"http://localhost:{os.getenv('LOCAL_DYNAMODB_PORT', '8002')}"
TRACE_TIMEOUT = int(os.getenv("E2E_PHOENIX_TRACE_TIMEOUT", "120"))
OPENER = build_opener(ProxyHandler({}))

STEP_PREFIX = "alert_review_workflow."
ROOT_NAME = "alert_review_workflow"
# Content that must never be exported (OTEL_CAPTURE_LLM_CONTENT stays false).
CONTENT_ATTRIBUTES = re.compile(
    r"^(input\.value|llm\.(input_messages|output_messages|prompts|prompt_template)|"
    r"gen_ai\.(prompt|completion|input\.messages|output\.messages))(\.|$)"
)


def http_json(url: str, *, auth: tuple[str, str] | None = None, body: Any = None) -> Any:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if auth:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    request = Request(url, data=data, headers=headers, method="POST" if body else "GET")
    with OPENER.open(request, timeout=30) as response:
        payload = response.read()
    return json.loads(payload) if payload else None


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, text=True)


def provision_manager() -> tuple[str, str]:
    """Create a throw-away manager inside the API container (no bootstrap token
    is configured locally, so the HTTP user endpoint is closed)."""
    email = f"e2e-phoenix-{secrets.token_hex(5)}@example.com"
    password = secrets.token_urlsafe(30)
    script = (
        "import os;"
        "from src.infrastructure.entrypoint.api.factories.local_auth_factory "
        "import get_register_local_user_use_case as f;"
        "from src.application.ports.local_auth_port import LocalRole;"
        "f().execute(email=os.environ['E2E_EMAIL'], name='E2E Phoenix', "
        "password=os.environ['E2E_PASSWORD'], role=LocalRole.MANAGER)"
    )
    subprocess.run(
        [
            "docker", "exec",
            "-e", f"E2E_EMAIL={email}", "-e", f"E2E_PASSWORD={password}",
            API_CONTAINER, "python", "-c", script,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return email, password


# ── Phoenix ─────────────────────────────────────────────────────────────


def phoenix_healthy() -> bool:
    try:
        with OPENER.open(f"{PHOENIX_URL}/healthz", timeout=5) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


def wait_phoenix_healthy(timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if phoenix_healthy():
            return
        time.sleep(2)
    raise E2EFailure(f"Phoenix no volvió a estar sano en {timeout}s")


def phoenix_project_id() -> str:
    projects = http_json(f"{PHOENIX_URL}/v1/projects")["data"]
    default = next((p for p in projects if p["name"] == "default"), None)
    require(default is not None, f"Phoenix sin proyecto 'default': {projects}")
    return default["id"]


_TRACE_QUERY = """
query Trace($project: ID!, $trace: ID!) {
  node(id: $project) {
    ... on Project {
      trace(traceId: $trace) {
        traceId
        numSpans
        spans(first: 500) {
          edges { node { name parentId statusCode attributes context { spanId traceId } } }
        }
      }
    }
  }
}
"""


def fetch_trace(project_id: str, trace_hex: str) -> list[dict[str, Any]]:
    """Spans of one trace as {name, span_id, parent_id, status, attributes(dict)}."""
    result = http_json(
        f"{PHOENIX_URL}/graphql",
        body={"query": _TRACE_QUERY, "variables": {"project": project_id, "trace": trace_hex}},
    )
    trace = ((result.get("data") or {}).get("node") or {}).get("trace")
    if not trace:
        return []
    spans = []
    for edge in trace["spans"]["edges"]:
        node = edge["node"]
        raw = node["attributes"]
        spans.append(
            {
                "name": node["name"],
                "span_id": node["context"]["spanId"],
                "trace_id": node["context"]["traceId"],
                "parent_id": node["parentId"],
                "status": node["statusCode"],
                "attributes": json.loads(raw) if isinstance(raw, str) else raw,
            }
        )
    return spans


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Phoenix returns attributes nested ({'aria': {'run_id': ...}}): flatten to dotted keys."""
    if isinstance(value, dict):
        flat: dict[str, Any] = {}
        for key, inner in value.items():
            flat.update(flatten(inner, f"{prefix}.{key}" if prefix else key))
        return flat
    return {prefix: value}


def wait_for_trace(project_id: str, trace_hex: str, step_count: int) -> list[dict[str, Any]]:
    """Wait until the Collector has delivered the whole trace (batching delay)."""
    deadline = time.monotonic() + TRACE_TIMEOUT
    spans: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        spans = fetch_trace(project_id, trace_hex)
        steps = [s for s in spans if s["name"].startswith(STEP_PREFIX)]
        root = [s for s in spans if s["name"] == ROOT_NAME]
        if root and len(steps) >= step_count:
            time.sleep(5)  # let late LLM/tool children of the last step land
            return fetch_trace(project_id, trace_hex)
        time.sleep(3)
    raise E2EFailure(
        f"Phoenix no recibió la traza {trace_hex} completa en {TRACE_TIMEOUT}s "
        f"(spans={[s['name'] for s in spans]}, pasos esperados={step_count})"
    )


# ── Persisted workflow data ─────────────────────────────────────────────


def persisted_steps(workflow_execution_id: str) -> list[dict[str, Any]]:
    import boto3
    from boto3.dynamodb.conditions import Key

    table = boto3.resource(
        "dynamodb",
        endpoint_url=DYNAMODB_URL,
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "local"),
    ).Table("workflow_step_executions")
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("workflow_execution_id").eq(workflow_execution_id)}
    while True:
        page = table.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


# ── Assertions ──────────────────────────────────────────────────────────


def verify_trace(
    spans: list[dict[str, Any]],
    workflow_id: str,
    steps: list[dict[str, Any]],
    sensitive: list[str],
) -> dict[str, int]:
    trace_hex = workflow_id.replace("-", "")
    flat = {s["span_id"]: {**s, "attributes": flatten(s["attributes"])} for s in spans}
    require(
        all(s["trace_id"] == trace_hex for s in spans),
        "Hay spans con un trace_id distinto del workflow_execution_id",
    )

    roots = [s for s in flat.values() if s["name"] == ROOT_NAME]
    require(len(roots) == 1, f"Se esperaba un solo span raíz del workflow, hay {len(roots)}")
    root = roots[0]
    require(
        root["parent_id"] not in flat,
        "El span raíz del workflow no debe colgar de otro span de la traza",
    )
    require(
        root["attributes"].get("aria.workflow.id") == workflow_id,
        "El span raíz no lleva aria.workflow.id",
    )

    step_spans = {
        s["attributes"].get("aria.workflow.step_id"): s
        for s in flat.values()
        if s["attributes"].get("aria.operation.type") == "workflow.step"
    }
    for step in steps:
        step_id = str(step["step_execution_id"])
        span = step_spans.get(step_id)
        require(
            span is not None,
            f"El paso persistido {step.get('step_name')} (step_id={step_id}) no está en Phoenix",
        )
        require(span["parent_id"] == root["span_id"], f"El paso {step_id} no cuelga del span raíz")
        require(
            span["attributes"].get("aria.workflow.step") == step["step_name"],
            f"aria.workflow.step distinto en {step_id}",
        )
        require(
            int(span["attributes"].get("aria.workflow.attempt", -1)) == int(step.get("attempt", 1)),
            f"aria.workflow.attempt distinto en {step_id}",
        )
    require(
        len(step_spans) == len(steps),
        f"Phoenix tiene {len(step_spans)} spans de paso y ARIA {len(steps)} ejecuciones",
    )

    def step_ancestor(span: dict[str, Any]) -> dict[str, Any] | None:
        seen: set[str] = set()
        current = span
        while current["parent_id"] in flat and current["parent_id"] not in seen:
            seen.add(current["parent_id"])
            current = flat[current["parent_id"]]
            if current["attributes"].get("aria.operation.type") == "workflow.step":
                return current
        return None

    counts = {"llm": 0, "tool": 0}
    run_ids: list[str] = []
    for span in flat.values():
        kind = span["attributes"].get("aria.operation.type")
        if kind not in counts:
            continue
        counts[kind] += 1
        run_id = span["attributes"].get("aria.run_id")
        require(bool(run_id), f"El span {kind} {span['name']} no lleva aria.run_id")
        run_ids.append(str(run_id))
        require(
            step_ancestor(span) is not None,
            f"El span {kind} {span['name']} no desciende de un paso del workflow",
        )
    require(counts["llm"] >= 1, "La traza no tiene ninguna llamada LLM")
    require(
        len(run_ids) == len(set(run_ids)),
        f"aria.run_id repetido (llamada duplicada): {sorted(run_ids)}",
    )
    if {"classification", "adversarial"} & {s["step_name"] for s in steps}:
        require(counts["tool"] >= 1, "El workflow llegó a clasificar y no hay span de herramienta")

    dump = json.dumps([s["attributes"] for s in flat.values()], ensure_ascii=False)
    for value in sensitive:
        require(
            not re.search(rf"(?<![\w.]){re.escape(value)}(?![\w.])", dump),
            f"Un dato sensible ({value[:3]}…) llegó a los atributos de los spans",
        )
    for span in flat.values():
        leaked = [k for k in span["attributes"] if CONTENT_ATTRIBUTES.search(k)]
        require(not leaked, f"El span {span['name']} exporta contenido: {leaked}")
        output = span["attributes"].get("output.value")
        if output is not None:
            require(
                set(json.loads(output) if isinstance(output, str) else output) <= {"model"},
                f"output.value de {span['name']} lleva algo más que el modelo",
            )
    return {**counts, "steps": len(step_spans), "spans": len(flat)}


def tempo_has_trace(trace_hex: str, timeout: int = 90) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            body = http_json(
                f"{GRAFANA_URL}/api/datasources/proxy/uid/tempo/api/traces/{trace_hex}",
                auth=GRAFANA_AUTH,
            )
            if body and (body.get("batches") or body.get("resourceSpans")):
                return True
        except (HTTPError, URLError, OSError, ValueError):
            pass
        time.sleep(3)
    return False


# ── Scenario ────────────────────────────────────────────────────────────


def run_alert(manager: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    event = e07.build_event()
    started = manager.request("POST", "/alerts/test", {"event": event}, expected=(202,))
    detail = e07.wait_for_workflow(manager, str(started["async_operation_id"]), str(started["alert_id"]))
    require(bool(detail.get("workflow_execution_id")), "El detalle no trae workflow_execution_id")
    return event, detail


def main() -> None:
    require(phoenix_healthy(), f"Phoenix no responde en {PHOENIX_URL}; levanta `make observability-up`")
    email, password = provision_manager()
    manager = e07.login(email, password)
    settings_before = manager.request("GET", "/operational-settings")
    phoenix_stopped = False
    try:
        settings = json.loads(json.dumps(settings_before))
        settings.update(agent_enabled=True, analyst_enabled=True, voicebot_enabled=False)
        manager.request(
            "PUT", "/operational-settings", {"settings": settings, "changed_by": "e2e-phoenix"}
        )
        project_id = phoenix_project_id()

        # 1-4. Real workflow -> trace identity, steps, LLM/tool spans, privacy.
        event, detail = run_alert(manager)
        workflow_id = str(detail["workflow_execution_id"])
        trace_hex = workflow_id.replace("-", "")
        steps = persisted_steps(workflow_id)
        require(len(steps) >= 5, f"Pocos pasos persistidos: {len(steps)}")
        spans = wait_for_trace(project_id, trace_hex, step_count=len(steps))
        sensitive = [
            event["customerid"], event["transactionid"], event["deviceid"],
            event["counterpartyentityid_encrypted"], str(event["amount_value"]),
        ]
        summary = verify_trace(spans, workflow_id, steps, sensitive)
        print(f"Phoenix trace {trace_hex}: {summary}")

        # 5. Fan-out: the same trace is in Tempo.
        require(tempo_has_trace(trace_hex), "La traza no llegó a Tempo (¿el Collector dejó de reenviar?)")
        print("Tempo: la misma traza está disponible")

        # 6. Persistence across a PostgreSQL + Phoenix restart.
        before = {s["span_id"] for s in spans}
        docker("restart", PHOENIX_DB_CONTAINER)
        docker("restart", PHOENIX_CONTAINER)
        wait_phoenix_healthy()
        after_spans: list[dict[str, Any]] = []
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not after_spans:
            after_spans = fetch_trace(project_id, trace_hex)
            if not after_spans:
                time.sleep(2)
        require({s["span_id"] for s in after_spans} == before, "Tras reiniciar Phoenix/PostgreSQL cambió la traza")
        print(f"Persistencia: {len(after_spans)} spans intactos tras reiniciar PostgreSQL y Phoenix")

        # 7. Phoenix down: the workflow and the other backends keep working.
        docker("stop", PHOENIX_CONTAINER)
        phoenix_stopped = True
        _, degraded = run_alert(manager)
        degraded_hex = str(degraded["workflow_execution_id"]).replace("-", "")
        require(degraded.get("workflow_status") == "SUCCEEDED", "Con Phoenix caído el workflow no terminó")
        require(tempo_has_trace(degraded_hex), "Con Phoenix caído la traza no llegó a Tempo")
        print("Con Phoenix caído: el workflow terminó y Tempo recibió su traza")
    finally:
        if phoenix_stopped:
            docker("start", PHOENIX_CONTAINER)
            wait_phoenix_healthy()
        manager.request(
            "PUT",
            "/operational-settings",
            {"settings": settings_before, "changed_by": "e2e-phoenix-restore"},
        )
    print("E13 Phoenix E2E OK")


if __name__ == "__main__":
    try:
        main()
    except (E2EFailure, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        print(f"E13 Phoenix E2E FAILED: {exc} {detail}", file=sys.stderr)
        raise SystemExit(1) from exc
