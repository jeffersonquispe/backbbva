"""Exercise E07 alert intake, automated processing, escalation and analyst resolution.

All API traffic goes through nginx's same-origin /api proxy. The script uses
only the standard library and never prints credentials or access tokens.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost").rstrip("/")
API = f"{BASE_URL}/api/v0"
OPENER = build_opener(ProxyHandler({}))
WORKFLOW_TIMEOUT = int(os.getenv("E2E_WORKFLOW_TIMEOUT", "600"))
POLL_INTERVAL = float(os.getenv("E2E_POLL_INTERVAL", "2"))


class E2EFailure(RuntimeError):
    pass


class Api:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        deadline = time.monotonic() + 120
        while True:
            request = Request(f"{API}{path}", data=body, headers=headers, method=method)
            try:
                with OPENER.open(request, timeout=45) as response:
                    status = response.status
                    content = response.read()
            except HTTPError as exc:
                status, content = exc.code, exc.read()
            except (URLError, TimeoutError) as exc:
                if time.monotonic() < deadline:
                    time.sleep(2)
                    continue
                raise E2EFailure(
                    f"{method} {path}: conexión fallida tras reintentos: {exc}"
                ) from exc
            if status not in (502, 503, 504) or time.monotonic() >= deadline:
                break
            time.sleep(2)
        try:
            result = json.loads(content) if content else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            result = content.decode(errors="replace")
        if status not in expected:
            detail = (
                result.get("detail", result) if isinstance(result, dict) else result
            )
            raise E2EFailure(f"{method} {path}: HTTP {status}: {detail}")
        return result


def login(email: str, password: str) -> Api:
    result = Api().request(
        "POST", "/auth/login", {"email": email, "password": password}
    )
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        raise E2EFailure("Login exitoso sin access_token")
    return Api(token)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise E2EFailure(message)


def wait_for_workflow(api: Api, operation_id: str, alert_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + WORKFLOW_TIMEOUT
    last_status = "unknown"
    while time.monotonic() < deadline:
        poll = api.request("GET", f"/async-operations/{operation_id}/poll")
        last_status = str(poll.get("status", "unknown"))
        if poll.get("done"):
            if last_status != "SUCCEEDED":
                raise E2EFailure(
                    f"Workflow finalizó como {last_status}: {poll.get('error')}"
                )
            break
        time.sleep(POLL_INTERVAL)
    else:
        raise E2EFailure(
            f"Timeout de {WORKFLOW_TIMEOUT}s esperando workflow; estado={last_status}, "
            f"alert_id={alert_id}, operation_id={operation_id}"
        )

    detail = api.request("GET", f"/analyst-queue/{alert_id}")
    steps = detail.get("steps") or []
    names = {step.get("step_name") or step.get("name") for step in steps}
    expected = {
        "pre_process",
        "detector",
        "detector_adversarial",
        "executor",
        "post_process",
    }
    reviews = [
        step for step in steps if step.get("step_name") == "detector_adversarial"
    ]
    review = max(reviews, key=lambda step: step.get("attempt", 1)) if reviews else {}
    decision = (review.get("output") or {}).get("decision")
    require(
        decision in {"pass", "scale_to_analyst", "handle_by_aria"},
        f"Primer adversarial sin una decisión válida: {decision!r}",
    )
    if decision == "handle_by_aria":
        expected |= {"classification", "adversarial", "analyst"}
    missing = expected - names
    require(
        not missing,
        f"Faltan pasos del workflow: {sorted(missing)}; encontrados={names}",
    )
    failed = [
        step
        for step in steps
        if (step.get("step_name") or step.get("name")) in expected
        and step.get("status") != "SUCCEEDED"
    ]
    require(not failed, f"Hay pasos requeridos fallidos: {failed}")
    return detail


def build_event() -> dict[str, Any]:
    now = datetime.now(UTC)
    event_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    prior_transactions = [
        {
            "event_time": (now - timedelta(minutes=2 * minute)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "amount": amount,
            "channel": "PSE",
            "beneficiary_id": "90123456789",
            "status": "approved",
        }
        for minute, amount in enumerate((185000, 240000, 315000, 410000), 1)
    ]
    event = {
        "eventid": str(uuid.uuid4()),
        "eventtype": "transferencia",
        "customerid": str(1000000000 + uuid.uuid4().int % 8999999999),
        "channel": "web",
        "amount_value": 520000,
        "fecha_transaccion": event_time,
        "integrationpoint": "PSE",
        "triggered_rules": "VELOCITY_03: 5 transacciones en los últimos 10 minutos, incluida la actual",
        "transactionid": str(uuid.uuid4()),
        "deviceid": str(uuid.uuid4()),
        "counterpartyentityid_encrypted": "90123456789",
        "biocatch_isMobileRat": "false",
        "biocatch_isEmulator": "false",
        "biocatch_isRat": "false",
        "biocatch_isBot": "false",
        "transacciones_json": json.dumps(prior_transactions),
    }
    return event


def wait_for_reasoning_evaluation(
    api: Api, alert_id: str, timeout_s: int = 90
) -> dict[str, Any]:
    """The LLM-judge runs in its own task after the workflow finishes; check its
    verdict (per step, versioned) through the API the alert detail uses."""
    deadline = time.monotonic() + timeout_s
    view: dict[str, Any] = {}
    while time.monotonic() < deadline:
        view = api.request("GET", f"/alerts/{alert_id}/reasoning-evaluation")
        if view.get("state") in {"evaluated", "invalid"}:
            break
        time.sleep(2)
    require(
        view.get("state") == "evaluated",
        f"El evaluador no emitió un veredicto válido: {view}",
    )
    evaluation = view["evaluation"]
    require(evaluation["prompt_version"] == "v3", "El veredicto no es del prompt v3")
    steps = {item["step"]: item for item in evaluation["steps"]}
    require("detector" in steps, f"Falta el veredicto por paso: {sorted(steps)}")
    require(
        steps["detector"]["hallucination"] is True
        and evaluation["hallucination"] is True
        and evaluation["data_use_correct"] is False,
        f"El veredicto global no se deriva de los pasos: {evaluation}",
    )
    require(
        any(not item["hallucination"] for item in steps.values()),
        "Debe haber al menos un paso sin alucinación",
    )
    criteria = {item["key"]: item for item in evaluation["criteria"]}
    require(
        criteria.get("clarity", {}).get("passed") is True
        and criteria.get("step_consistency", {}).get("passed") is False
        and "model_alignment" in criteria
        and criteria["model_alignment"]["passed"] is None,
        f"Los criterios de explicabilidad no llegaron como se esperaba: {criteria}",
    )
    job = view["job"]
    require(job is not None, "El veredicto no trae el estado del job del evaluador")
    require(
        job["status"] == "evaluated" and job["requested_by"] == "workflow",
        f"Estado del job inesperado: {job}",
    )
    # How long the evaluator takes end to end (queue wait + judge) with the scripted
    # LLM, i.e. the overhead of the flow itself: a regression here means the queue,
    # the worker or the job bookkeeping got slower, whatever the real model does.
    budget_ms = int(os.getenv("E2E_JUDGE_MAX_TOTAL_MS", "60000"))
    require(
        job["wait_ms"] is not None and job["total_ms"] is not None,
        f"El job no registró sus tiempos: {job}",
    )
    require(
        job["total_ms"] <= budget_ms,
        f"El evaluador tardó {job['total_ms']} ms de punta a punta (máx {budget_ms} ms)",
    )
    require(
        evaluation["duration_ms"] >= 0 and job["run_ms"] == evaluation["duration_ms"],
        "El tiempo del juez del veredicto y del job no coinciden",
    )
    # Verdict days are Bogotá days, not UTC days.
    bogota_today = datetime.now(ZoneInfo("America/Bogota")).date()
    from_day = (bogota_today - timedelta(days=1)).isoformat()
    to_day = bogota_today.isoformat()
    listed = api.request(
        "GET",
        f"/metrics/reasoning-evaluations?from_day={from_day}&to_day={to_day}"
        "&hallucination=true&limit=200",
    )
    require(
        alert_id in {str(item["alert_id"]) for item in listed},
        "La alerta marcada no aparece en el listado filtrado",
    )
    return {
        "state": view["state"],
        "hallucination": evaluation["hallucination"],
        "data_use_correct": evaluation["data_use_correct"],
        "steps": {name: item["hallucination"] for name, item in steps.items()},
        "prompt_version": evaluation["prompt_version"],
        "criteria": {key: item["passed"] for key, item in criteria.items()},
        "timings_ms": {
            "wait": job["wait_ms"],
            "judge": job["run_ms"],
            "total": job["total_ms"],
        },
    }


def check_evaluator_independence(manager: Api, analyst: Api) -> dict[str, Any]:
    """With the evaluator's worker STOPPED, an alert is still processed, escalated and
    visible to the analyst; its evaluation just waits, and completes once the worker is
    back. The alert never depends on the evaluator."""
    container = os.getenv("E2E_EVALUATION_WORKER_CONTAINER", "aria-evaluation-worker")
    subprocess.run(["docker", "stop", container], check=True, capture_output=True)
    try:
        started = manager.request(
            "POST", "/alerts/test", {"event": build_event()}, expected=(202,)
        )
        alert_id = str(started["alert_id"])
        detail = wait_for_workflow(
            manager, str(started["async_operation_id"]), alert_id
        )
        require(
            detail.get("status") == "ESCALATED",
            "Con el evaluador caído la alerta no escaló",
        )
        require(
            detail.get("workflow_status") == "SUCCEEDED",
            "El workflow dependió del evaluador",
        )
        queue = analyst.request("GET", "/analyst-queue")
        require(
            alert_id in {str(item.get("alert_id")) for item in queue},
            "La alerta no es visible para el analista con el evaluador caído",
        )
        waiting = manager.request("GET", f"/alerts/{alert_id}/reasoning-evaluation")
        require(
            waiting["state"] not in {"evaluated", "invalid", "running"},
            f"Algo evaluó la alerta con el worker detenido: {waiting}",
        )
    finally:
        subprocess.run(["docker", "start", container], check=True, capture_output=True)
    verdict = wait_for_reasoning_evaluation(manager, alert_id, timeout_s=120)
    return {
        "alert_status_while_evaluator_down": detail.get("status"),
        "state_while_evaluator_down": waiting["state"],
        "state_after_restart": verdict["state"],
    }


def main() -> None:
    manager_email = os.getenv("E2E_MANAGER_EMAIL")
    manager_password = os.getenv("E2E_MANAGER_PASSWORD")
    analyst_email = os.getenv("E2E_FRAUD_ANALYST_EMAIL")
    analyst_password = os.getenv("E2E_FRAUD_ANALYST_PASSWORD")
    if not all((manager_email, manager_password, analyst_email, analyst_password)):
        raise E2EFailure(
            "Configura E2E_MANAGER_EMAIL/PASSWORD y E2E_FRAUD_ANALYST_EMAIL/PASSWORD"
        )

    manager = login(manager_email, manager_password)
    analyst = login(analyst_email, analyst_password)
    settings_before = manager.request("GET", "/operational-settings")
    alert_id = str(uuid.uuid4())
    settings_changed = False
    try:
        # Keep analyst capacity available so the real workflow can route to a
        # human. Disable voicebot to keep the E2E path focused on E07.
        settings_for_e2e = json.loads(json.dumps(settings_before))
        settings_for_e2e["agent_enabled"] = True
        settings_for_e2e["analyst_enabled"] = True
        settings_for_e2e["voicebot_enabled"] = False
        # Judge every finished alert so the LLM-judge verdict can be verified.
        settings_for_e2e["reasoning_evaluation_sample_rate"] = 1.0
        manager.request(
            "PUT",
            "/operational-settings",
            {"settings": settings_for_e2e, "changed_by": "e2e-e07"},
        )
        settings_changed = True

        # This denial proves the queue's write operations enforce the human
        # fraud-analyst role. Manager credentials are intentionally used here.
        manager.request(
            "POST",
            f"/analyst-queue/{alert_id}/take",
            {},
            expected=(403,),
        )

        event = build_event()
        started = manager.request(
            "POST",
            "/alerts/test",
            {"event": event},
            expected=(202,),
        )
        alert_id = str(started["alert_id"])
        operation_id = str(started["async_operation_id"])
        require(started.get("status") == "DISPATCHED", "La alerta no se despachó")
        detail = wait_for_workflow(manager, operation_id, alert_id)
        require(detail.get("alert_id") == alert_id, "Detalle de otra alerta recibido")
        require(detail.get("status") == "ESCALATED", "La alerta no quedó escalada")
        require(
            detail.get("workflow_status") == "SUCCEEDED",
            "El workflow no terminó con éxito",
        )
        workflow_output = detail.get("workflow_output") or {}
        require(
            workflow_output.get("status") == "success",
            f"El resultado del workflow no es terminal exitoso: {workflow_output}",
        )
        executor_steps = [
            step
            for step in detail.get("steps", [])
            if step.get("step_name") == "executor"
        ]
        require(
            bool(executor_steps)
            and (executor_steps[-1].get("output") or {}).get("executed_action")
            == "scale_to_analyst",
            f"El ejecutor no escaló a analista: {executor_steps}",
        )

        verdict = wait_for_reasoning_evaluation(manager, alert_id)

        queue = analyst.request("GET", "/analyst-queue")
        queued = {str(item.get("alert_id")) for item in queue}
        require(alert_id in queued, "La alerta escalada no aparece en la cola")

        # Restore the shared settings before exercising analyst operations.
        manager.request(
            "PUT",
            "/operational-settings",
            {"settings": settings_before, "changed_by": "e2e-e07-capacity-restore"},
        )
        settings_changed = False

        taken = analyst.request("POST", f"/analyst-queue/{alert_id}/take", {})
        require(
            taken.get("status") == "ACTIVE", "La reserva del analista no quedó activa"
        )
        require(taken.get("holder") is not None, "La reserva no identifica al analista")

        resolved = analyst.request(
            "POST",
            f"/analyst-queue/{alert_id}/resolve",
            {"decision": "pass", "notes": "E07 E2E: resolución controlada"},
        )
        require(
            resolved.get("status") == "RELEASED", "La reserva no se liberó al resolver"
        )
        require(
            (resolved.get("detail") or {}).get("decision") == "pass",
            "La decisión del analista no quedó registrada",
        )

        final_queue = analyst.request("GET", "/analyst-queue")
        require(
            alert_id not in {str(item.get("alert_id")) for item in final_queue},
            "La alerta resuelta sigue en la cola",
        )
        independence = check_evaluator_independence(manager, analyst)

        final_detail = analyst.request("GET", f"/analyst-queue/{alert_id}")
        require(final_detail.get("status") == "CLOSED", "La alerta no quedó CLOSED")
        require(
            final_detail.get("workflow_status") == "SUCCEEDED",
            "El workflow persistido no quedó SUCCEEDED",
        )
        successful_steps = sorted(
            step.get("step_name")
            for step in final_detail.get("steps", [])
            if step.get("status") == "SUCCEEDED"
        )
        result = {
            "scenario": "E07 alert processing and analyst attention",
            "input": event,
            "output": {
                "alert_id": alert_id,
                "async_operation_id": operation_id,
                "workflow_status": final_detail.get("workflow_status"),
                "workflow_output": final_detail.get("workflow_output"),
                "steps_succeeded": successful_steps,
                "executor_action": "scale_to_analyst",
                "analyst_decision": (resolved.get("detail") or {}).get("decision"),
                "reservation_status": resolved.get("status"),
                "final_alert_status": final_detail.get("status"),
                "present_in_queue_after_resolution": False,
                "reasoning_evaluation": verdict,
                "evaluator_independence": independence,
            },
        }
        print("E07 E2E OK\n" + json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if settings_changed:
            manager.request(
                "PUT",
                "/operational-settings",
                {"settings": settings_before, "changed_by": "e2e-e07-restore"},
            )


if __name__ == "__main__":
    try:
        main()
    except (E2EFailure, KeyError, TypeError, ValueError) as exc:
        print(f"E07 E2E FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
