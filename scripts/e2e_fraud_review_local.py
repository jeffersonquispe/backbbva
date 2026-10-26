"""Run the E08 browser/API workflow with an ephemeral local bootstrap token."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from e2e_run_history import run as run_with_history

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "frontend_mockup"
COMPOSE_FILE = os.getenv(
    "LOCAL_DOCKER_COMPOSE_FILE", "deploy/local/docker/docker-compose.yml"
)
PROJECT = os.getenv("LOCAL_DOCKER_PROJECT", "aria-local")
BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost").rstrip("/")
API_HEALTH_URL = f"{BASE_URL}/health"
EMAIL = "e2e-fraud-review@aria.local"

opener = build_opener(ProxyHandler({}))


def compose_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        GENAI_ENVIRONMENT=os.getenv("LOCAL_DOCKER_ENV", "local"),
        LOCAL_DOCKER_PROJECT=PROJECT,
    )
    return env


def compose(*args: str, env: dict[str, str]) -> None:
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", COMPOSE_FILE, *args],
        cwd=ROOT,
        env=env,
        check=True,
    )


def read_existing_bootstrap_token(env: dict[str, str]) -> str:
    container = subprocess.check_output(
        ["docker", "compose", "-p", PROJECT, "-f", COMPOSE_FILE, "ps", "-q", "api"],
        cwd=ROOT,
        env=env,
        text=True,
    ).strip()
    if not container:
        return ""
    config = json.loads(
        subprocess.check_output(
            ["docker", "inspect", container], cwd=ROOT, env=env, text=True
        )
    )[0]
    for item in config["Config"].get("Env", []):
        if item.startswith("AUTH_BOOTSTRAP_TOKEN="):
            return item.partition("=")[2]
    return ""


def wait_for_api() -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            request = Request(API_HEALTH_URL)
            with opener.open(request, timeout=3) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(2)
    raise RuntimeError(f"API no quedó saludable detrás de nginx en {API_HEALTH_URL}")


def main() -> int:
    env = compose_environment()
    original_bootstrap = read_existing_bootstrap_token(env)
    temporary_bootstrap = secrets.token_urlsafe(36)
    test_password = f"E08-{secrets.token_urlsafe(24)}"
    frontend_env = env | {
        "AUTH_BOOTSTRAP_TOKEN": temporary_bootstrap,
        "E2E_BOOTSTRAP_TOKEN": temporary_bootstrap,
        "E2E_FRAUD_REVIEW_EMAIL": EMAIL,
        "E2E_FRAUD_REVIEW_PASSWORD": test_password,
        "ARIA_E2E_REAL": "1",
        "ARIA_E2E_BASE_URL": BASE_URL,
    }

    print("E08: habilitando aprovisionamiento efímero y preparando manager de prueba…")
    try:
        compose(
            "up", "-d", "--force-recreate", "api",
            env=env | {"AUTH_BOOTSTRAP_TOKEN": temporary_bootstrap},
        )
        wait_for_api()
        print("E08: ejecutando el flujo Playwright contra nginx/API local…")
        result = run_with_history(
            "playwright:e2e/fraud-review-real.spec.ts",
            "e2e/fraud-review-real.spec.ts",
            ["./node_modules/.bin/playwright", "test", "e2e/fraud-review-real.spec.ts"],
            frontend_env,
        )
        return result
    finally:
        print("E08: restaurando la configuración original del aprovisionamiento…")
        compose(
            "up", "-d", "--force-recreate", "api",
            env=env | {"AUTH_BOOTSTRAP_TOKEN": original_bootstrap},
        )
        wait_for_api()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"E08 local runner: {exc}", file=sys.stderr)
        sys.exit(1)
