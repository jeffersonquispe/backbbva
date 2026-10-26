"""Run real Playwright coverage for observability through local nginx."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "frontend_mockup"
PROJECT = os.getenv("LOCAL_DOCKER_PROJECT", "aria-local")
COMPOSE_FILE = os.getenv(
    "LOCAL_DOCKER_COMPOSE_FILE", "deploy/local/docker/docker-compose.yml"
)
BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost").rstrip("/")
EMAIL = "e2e-observability@example.com"
RELEASE_EMAIL = "e2e-release@example.com"
ROLE_USERS = {
    "E2E_CHANNEL_MANAGER": ("e2e-channel-manager@example.com", "E2E Channel Manager", "channel_manager"),
    "E2E_DATA_ANALYST": ("e2e-data-analyst@example.com", "E2E Data Analyst", "data_analyst"),
    "E2E_FRAUD_ANALYST": ("e2e-fraud-analyst@example.com", "E2E Fraud Analyst", "fraud_analyst"),
    "E2E_OPS_ANALYST": ("e2e-ops-analyst@example.com", "E2E Ops Analyst", "ops_analyst"),
}
opener = build_opener(ProxyHandler({}))


def compose(*args: str, env: dict[str, str]) -> None:
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", COMPOSE_FILE, *args],
        cwd=ROOT,
        env=env,
        check=True,
    )


def bootstrap_token(env: dict[str, str]) -> str:
    container = subprocess.check_output(
        ["docker", "compose", "-p", PROJECT, "-f", COMPOSE_FILE, "ps", "-q", "api"],
        cwd=ROOT,
        env=env,
        text=True,
    ).strip()
    if not container:
        return ""
    config = json.loads(
        subprocess.check_output(["docker", "inspect", container], cwd=ROOT, env=env)
    )[0]
    return next(
        (
            item.partition("=")[2]
            for item in config["Config"].get("Env", [])
            if item.startswith("AUTH_BOOTSTRAP_TOKEN=")
        ),
        "",
    )


def api(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, object]:
    request = Request(
        f"{BASE_URL}/api/v0{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={
            "X-Bootstrap-Token": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with opener.open(request, timeout=20) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def provision_user(token: str, email: str, name: str, role: str) -> str:
    password = f"E2E-{secrets.token_urlsafe(28)}"
    status, users = api("GET", "/auth/users", token)
    if status != 200:
        raise RuntimeError(f"Could not list local users with bootstrap token: HTTP {status}")
    user = next((item for item in users if item["email"] == email), None)
    if user:
        status, _ = api(
            "PUT",
            f"/auth/users/{user['id']}/password",
            token,
            {"password": password},
        )
    else:
        status, _ = api(
            "POST",
            "/auth/users",
            token,
            {"email": email, "password": password, "name": name, "role": role},
        )
    if status not in (200, 201):
        raise RuntimeError(f"Could not provision local {role}: HTTP {status}")
    return password


def wait_for_api() -> None:
    for _ in range(60):
        try:
            with opener.open(f"{BASE_URL}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(2)
    raise RuntimeError(f"API was not healthy behind nginx at {BASE_URL}")


def main() -> int:
    env = os.environ.copy()
    env.update(
        GENAI_ENVIRONMENT=os.getenv("LOCAL_DOCKER_ENV", "local"),
        LOCAL_DOCKER_PROJECT=PROJECT,
    )
    original = bootstrap_token(env)
    temporary = secrets.token_urlsafe(40)
    try:
        compose("up", "-d", "--force-recreate", "api", env=env | {"AUTH_BOOTSTRAP_TOKEN": temporary})
        subprocess.run(
            ["docker", "compose", "up", "-d", "--force-recreate", "web"],
            cwd=FRONTEND,
            env=env,
            check=True,
        )
        wait_for_api()
        password = provision_user(temporary, EMAIL, "E2E Observability", "manager")
        playwright_env = {
            "E2E_MANAGER_EMAIL": EMAIL,
            "E2E_MANAGER_PASSWORD": password,
        }
        if os.getenv("E2E_FULL_SUITE") == "1":
            release_password = provision_user(
                temporary, RELEASE_EMAIL, "E2E Release Manager", "release_manager"
            )
            playwright_env.update(
                {
                    "E2E_RELEASE_MANAGER_EMAIL": RELEASE_EMAIL,
                    "E2E_RELEASE_MANAGER_PASSWORD": release_password,
                    "E2E_FRAUD_REVIEW_EMAIL": "e2e-fraud-review@example.com",
                    "E2E_BOOTSTRAP_TOKEN": temporary,
                }
            )
            for env_prefix, (email, name, role) in ROLE_USERS.items():
                role_password = provision_user(temporary, email, name, role)
                playwright_env.update(
                    {
                        f"{env_prefix}_EMAIL": email,
                        f"{env_prefix}_PASSWORD": role_password,
                    }
                )
            if os.getenv("E2E_ISOLATE_WORKER_USERS") == "1":
                worker_count = int(os.getenv("E2E_PLAYWRIGHT_WORKERS", "1"))
                if not 1 <= worker_count <= 11:
                    raise RuntimeError("Isolated E2E worker users support 1 to 11 workers")
                for worker_index in range(worker_count):
                    for role_key, role, label in (
                        ("CHANNEL_MANAGER", "channel_manager", "Channel Manager"),
                        ("MANAGER", "manager", "Manager"),
                    ):
                        email = (
                            f"e2e-pw-worker-{worker_index}-{role_key.lower()}@example.com"
                        )
                        password = provision_user(
                            temporary,
                            email,
                            f"E2E Playwright worker {worker_index} {label}",
                            role,
                        )
                        prefix = f"E2E_{role_key}_W{worker_index}"
                        playwright_env.update(
                            {
                                f"{prefix}_EMAIL": email,
                                f"{prefix}_PASSWORD": password,
                            }
                        )
            fraud_review_password = provision_user(
                temporary,
                playwright_env["E2E_FRAUD_REVIEW_EMAIL"],
                "ARIA E08 fraud-review E2E",
                "manager",
            )
            playwright_env["E2E_FRAUD_REVIEW_PASSWORD"] = fraud_review_password
            seed_result = subprocess.run(
                [sys.executable, "scripts/e2e_api_seed.py"],
                cwd=ROOT,
                env=env | playwright_env | {"E2E_BASE_URL": BASE_URL},
                capture_output=True,
                text=True,
                check=False,
            )
            print(seed_result.stdout, end="")
            if seed_result.returncode:
                raise RuntimeError(seed_result.stderr or "E2E API seed failed")
            deploy_target = next(
                (
                    line.partition("=")[2]
                    for line in seed_result.stdout.splitlines()
                    if line.startswith("E2E_DEPLOY_TARGET=")
                ),
                "",
            )
            deploy_configuration_id, separator, deploy_version = deploy_target.rpartition(":")
            if not separator or not deploy_configuration_id or not deploy_version:
                raise RuntimeError("E2E seed did not return a deployment target")
            playwright_env.update(
                {
                    "E2E_DEPLOY_CONFIGURATION_ID": deploy_configuration_id,
                    "E2E_DEPLOY_VERSION": deploy_version,
                }
            )
        selected_test_files = os.getenv("E2E_TEST_FILES", "").split()
        playwright_command = ["./node_modules/.bin/playwright", "test"]
        if selected_test_files:
            playwright_command.extend(selected_test_files)
        elif os.getenv("E2E_FULL_SUITE") != "1":
            playwright_command.append("e2e/observability-real.spec.ts")
        suite_specs = " ".join(selected_test_files) or (
            "all specs" if os.getenv("E2E_FULL_SUITE") == "1" else "e2e/observability-real.spec.ts"
        )
        suite_label = "playwright:" + suite_specs
        history_command = [
            sys.executable,
            str(ROOT / "scripts" / "e2e_run_history.py"),
            "--label",
            suite_label,
            "--specs",
            suite_specs,
            "--",
            *playwright_command,
        ]
        result = subprocess.run(
            history_command,
            cwd=FRONTEND,
            env=env
            | playwright_env
            | {"ARIA_E2E_REAL": "1", "ARIA_E2E_BASE_URL": BASE_URL},
            check=False,
        )
        return result.returncode
    finally:
        if os.getenv("E2E_DUMP_API_LOGS") == "1":
            logs = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    PROJECT,
                    "-f",
                    COMPOSE_FILE,
                    "logs",
                    "--tail",
                    "3000",
                    "api",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            Path("/private/tmp/aria-e2e-api.log").write_text(
                logs.stdout, encoding="utf-8"
            )
            for line in logs.stdout.splitlines():
                if any(
                    marker in line
                    for marker in (
                        "configuration-deploy-requests",
                        "Unexpected error",
                        "Traceback",
                        "Exception:",
                    )
                ):
                    print(line)
        compose("up", "-d", "--force-recreate", "api", env=env | {"AUTH_BOOTSTRAP_TOKEN": original})
        subprocess.run(
            ["docker", "compose", "up", "-d", "--force-recreate", "web"],
            cwd=FRONTEND,
            env=env,
            check=True,
        )
        wait_for_api()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Observability E2E: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
