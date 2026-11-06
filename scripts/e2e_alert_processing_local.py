"""Run E07 with the local scripted LLM adapter and restore local settings."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/local/config.cfg"
WORKER = os.getenv("E2E_WORKER_CONTAINER", "aria-worker-main")
# The LLM-judge runs in its own worker: it needs the scripted backend too.
EVALUATION_WORKER = os.getenv(
    "E2E_EVALUATION_WORKER_CONTAINER", "aria-evaluation-worker"
)
WORKERS = (WORKER, EVALUATION_WORKER)


def _run(
    command: list[str], *, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )


def _require_local_api() -> None:
    result = _run(
        [
            "docker",
            "inspect",
            "aria-api",
            "--format",
            "{{range .Config.Env}}{{println .}}{{end}}",
        ],
        capture=True,
    )
    values = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    if values.get("GENAI_ENVIRONMENT") != "local":
        raise RuntimeError("E07 scripted LLM backend requires the local aria-api")


def _select_scripted_backend(original: bytes) -> None:
    text = original.decode("utf-8")
    for key, value in (
        ("LLM_BACKEND", "scripted_e2e"),
        ("PROFILING_BACKEND", "deterministic"),
    ):
        pattern = rf"(?m)^{key}=.*$"
        if not re.search(pattern, text):
            raise RuntimeError(f"Missing {key} in config/local/config.cfg")
        text = re.sub(pattern, f"{key}={value}", text, count=1)
    CONFIG.write_text(text)


def _wait_for_worker_backend(container: str) -> None:
    probe = (
        "from src.infrastructure.core.config import genai_config; "
        "from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory; "
        "print(genai_config.LLM_BACKEND, type(get_llm_unit_of_work_factory()).__name__)"
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", container, "python", "-c", probe],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if (
            result.returncode == 0
            and "scripted_e2e ScriptedE2ELLMUnitOfWorkFactory" in result.stdout
        ):
            return
        time.sleep(2)
    raise RuntimeError(
        f"{container} did not load the scripted_e2e backend within 90 seconds"
    )


def main() -> int:
    original = CONFIG.read_bytes()
    _require_local_api()
    try:
        _select_scripted_backend(original)
        for container in WORKERS:
            for source in (
                "src/infrastructure/llm/scripted_e2e.py",
                "src/infrastructure/llm/langchain/__init__.py",
            ):
                _run(
                    ["docker", "cp", str(ROOT / source), f"{container}:/code/{source}"]
                )
            _run(["docker", "restart", container])
        for container in WORKERS:
            _wait_for_worker_backend(container)
        env = os.environ.copy()
        env["E2E_BASE_URL"] = env.get("E2E_BASE_URL", "http://localhost")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/e2e_alert_processing.py")],
            cwd=ROOT,
            env=env,
            check=False,
        )
        return result.returncode
    finally:
        CONFIG.write_bytes(original)
        for container in WORKERS:
            _run(["docker", "restart", container])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"E07 local runner failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
