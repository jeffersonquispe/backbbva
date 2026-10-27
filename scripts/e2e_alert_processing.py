"""Exercise E07 alert intake, automated processing, escalation and analyst resolution.

All API traffic goes through nginx's same-origin /api proxy. The script uses
only the standard library and never prints credentials or access tokens.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

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
