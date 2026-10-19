"""Exercise the agent API and Celery recovery through local nginx."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import boto3
from boto3.dynamodb.conditions import Attr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.normpath(os.path.join(ROOT, "..", "frontend_mockup"))
COMPOSE_FILE = "deploy/local/docker/docker-compose.yml"
PROJECT = os.getenv("LOCAL_DOCKER_PROJECT", "aria-local")
BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost").rstrip("/")
API = f"{BASE_URL}/api/v0"
EMAIL = f"e2e-agent-{secrets.token_hex(6)}@example.com"
opener = build_opener(ProxyHandler({}))


def compose(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(
        ["docker", "compose", "-p", PROJECT, "-f", COMPOSE_FILE, *args],
        cwd=ROOT,
        env=env,
        text=True,
    ).strip()


def request(
    method: str,
    path: str,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    bootstrap: str | None = None,
) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if bootstrap:
        headers["X-Bootstrap-Token"] = bootstrap
    outgoing = Request(
        f"{API}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers=headers,
    )
    try:
        with opener.open(outgoing, timeout=20) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except HTTPError as error:
        payload = error.read()
        try:
            decoded = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            decoded = payload.decode(errors="replace")
        return error.code, decoded


def check(status: int, expected: int, label: str, payload: Any) -> Any:
    if status != expected:
        raise RuntimeError(
            f"{label}: expected HTTP {expected}, received {status} ({payload})"
        )
    return payload


def bootstrap_token() -> str:
    container_id = compose("ps", "-q", "api")
    details = json.loads(
        subprocess.check_output(["docker", "inspect", container_id], text=True)
    )[0]
    token = next(
        (
            value.partition("=")[2]
            for value in details["Config"].get("Env", [])
            if value.startswith("AUTH_BOOTSTRAP_TOKEN=")
        ),
        "",
    )
    return token


def restart_nginx() -> None:
    subprocess.run(
        ["docker", "compose", "restart", "web"], cwd=FRONTEND, check=True
    )


def wait_for_nginx_api() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with opener.open(f"{BASE_URL}/health", timeout=3) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError("API did not become healthy through nginx")


def manager_token(bootstrap: str) -> tuple[str, str]:
    password = secrets.token_urlsafe(30)
    status, users = request("GET", "/auth/users", bootstrap=bootstrap)
    check(status, 200, "list users", users)
    user = next((item for item in users if item["email"] == EMAIL), None)
    if user:
        status, _ = request(
            "PUT",
            f"/auth/users/{user['id']}/password",
            body={"password": password},
            bootstrap=bootstrap,
        )
        check(status, 200, "reset E2E user password", None)
    else:
        status, _ = request(
            "POST",
            "/auth/users",
            body={
                "email": EMAIL,
                "password": password,
                "name": "Agent E2E Manager",
                "role": "manager",
            },
            bootstrap=bootstrap,
        )
        check(status, 201, "create E2E user", None)
    status, login = request(
        "POST", "/auth/login", body={"email": EMAIL, "password": password}
    )
    check(status, 200, "login", login)
    return login["access_token"], user["id"] if user else login["id"]


def wait_for_session(token: str, session_id: str, status_name: str, timeout: int = 30) -> dict:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, latest = request("GET", f"/agent/sessions/{session_id}", token)
        if status == 200 and latest.get("status") == status_name:
            return latest
        time.sleep(0.25)
    raise RuntimeError(f"agent session did not reach {status_name}")


def create_session(token: str) -> str:
    status, session = request(
        "POST",
        "/agent/sessions",
        token,
        {"mode": "assistant", "scope": ["configuration"], "requested_budget": {}},
    )
    check(status, 201, "create agent session", session)
    return session["session_id"]


def exercise_versioned_objective_api(token: str) -> None:
    status, versions = request("GET", "/agent/objectives", token)
    check(status, 200, "list objective versions", versions)
    status, active = request("GET", "/agent/objectives/active", token)
    if status not in {200, 404}:
        check(status, 200, "read active objective", active)
    expected_active_version = active["version"] if status == 200 else None
    status, draft = request("POST", "/agent/objectives", token, {})
    check(status, 201, "create objective version", draft)
    if draft["status"] != "DRAFT" or draft["version"] <= len(versions):
        raise RuntimeError("objective version was not created as a new immutable draft")
    status, activated = request(
        "POST",
        f"/agent/objectives/{draft['version']}/activate",
        token,
        {"expected_active_version": expected_active_version},
    )
    check(status, 200, "activate objective version", activated)
    if activated["status"] != "ACTIVE":
        raise RuntimeError("objective activation did not become active")


def update_settings(token: str, settings: dict[str, Any]) -> None:
    status, _ = request(
        "PUT", "/assistant-optimizer-settings", token, {"settings": settings}
    )
    check(status, 200, "update assistant settings", None)


def run_statuses(session_id: str) -> set[str]:
    client = boto3.resource(
        "dynamodb",
        endpoint_url=f"http://localhost:{os.getenv('LOCAL_DYNAMODB_PORT', '8002')}",
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    response = client.Table("agent_runs").scan(
        FilterExpression=Attr("session_id").eq(session_id)
    )
    return {str(row["status"]) for row in response.get("Items", [])}


def wait_for_run(session_id: str, expected: str, timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if expected in run_statuses(session_id):
            return
        time.sleep(0.1)
    raise RuntimeError(f"agent run did not reach {expected}")


def main() -> int:
    original_bootstrap = bootstrap_token()
    temporary_bootstrap = secrets.token_urlsafe(40)
    original_settings: dict[str, Any] | None = None
    token: str | None = None
    worker_stopped = False
    try:
        compose(
            "up",
            "-d",
            "--force-recreate",
            "api",
            env=os.environ | {"AUTH_BOOTSTRAP_TOKEN": temporary_bootstrap},
        )
        restart_nginx()
        wait_for_nginx_api()
        token, _user_id = manager_token(temporary_bootstrap)
        exercise_versioned_objective_api(token)
        status, original_settings = request(
            "GET", "/assistant-optimizer-settings", token
        )
        check(status, 200, "read assistant settings", original_settings)
        update_settings(
            token,
            dict(original_settings, max_sessions_per_user=100),
        )
        # Kill switch is read by the real Celery task after it is dequeued.
        kill_session = create_session(token)
        compose("stop", "aria-agent-worker")
        worker_stopped = True
        status, _ = request("POST", f"/agent/sessions/{kill_session}/start", token)
        check(status, 200, "start kill-switch session", None)
        disabled = dict(original_settings, assistant_enabled=False)
        update_settings(token, disabled)
        compose("start", "aria-agent-worker")
        worker_stopped = False
        wait_for_session(token, kill_session, "PAUSED")
        update_settings(token, original_settings)

        # Cancellation while queued must remain terminal when the worker sees it.
        cancel_session = create_session(token)
        compose("stop", "aria-agent-worker")
        worker_stopped = True
        status, _ = request("POST", f"/agent/sessions/{cancel_session}/start", token)
        check(status, 200, "start cancellation session", None)
        status, _ = request("POST", f"/agent/sessions/{cancel_session}/cancel", token)
        check(status, 200, "cancel session", None)
        compose("start", "aria-agent-worker")
        worker_stopped = False
        wait_for_session(token, cancel_session, "CANCELLED")

        # A long-running local stub makes killing the actual worker deterministic.
        os.environ["AGENT_STUB_DELAY_SECONDS"] = "2"
        compose("up", "-d", "--force-recreate", "aria-agent-worker")
        recovery_session = create_session(token)
        status, _ = request("POST", f"/agent/sessions/{recovery_session}/start", token)
        check(status, 200, "start recovery session", None)
        wait_for_run(recovery_session, "RUNNING")
        compose("kill", "-s", "SIGKILL", "aria-agent-worker")
        compose("start", "aria-agent-worker")
        worker_stopped = False
        wait_for_run(recovery_session, "FAILED", timeout=150)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status, packages = request(
                "GET", f"/agent/sessions/{recovery_session}/packages", token
            )
            if status == 200 and packages:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("recovered session did not produce a package")
        if "SUCCEEDED" not in run_statuses(recovery_session):
            raise RuntimeError("recovered session did not complete a later run")
        print("Agent E2E por nginx: kill switch, cancelación y recuperación pasaron.")
        return 0
    finally:
        if token and original_settings is not None:
            update_settings(token, original_settings)
        if worker_stopped:
            compose("start", "aria-agent-worker")
        compose(
            "up",
            "-d",
            "--force-recreate",
            "api",
            env=os.environ | {"AUTH_BOOTSTRAP_TOKEN": original_bootstrap},
        )
        restart_nginx()


if __name__ == "__main__":
    raise SystemExit(main())
