"""Ratchet for static checks: fail when the error count grows past the baseline.

    python scripts/lint_ratchet.py ruff            # check
    python scripts/lint_ratchet.py mypy            # check
    python scripts/lint_ratchet.py ruff mypy --update   # rewrite the baseline

The baseline lives in ``.lint-baseline.json`` at the repo root. It records the
tool version it was produced with: counts are only comparable between the same
ruff/mypy versions, so a version mismatch is reported instead of silently
passing or failing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = ROOT / ".lint-baseline.json"

COMMANDS: dict[str, list[str]] = {
    "ruff": [
        "ruff",
        "check",
        "src",
        "tests",
        "scripts",
        "--output-format=json",
        "--exit-zero",
    ],
    "mypy": ["mypy", "--config-file", "mypy.ini", "--no-error-summary"],
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        sys.exit(f"'{cmd[0]}' is not installed in this environment.")


def tool_version(tool: str) -> str:
    return _run([tool, "--version"]).stdout.strip().split("(")[0].strip()


def count_errors(tool: str) -> int:
    result = _run(COMMANDS[tool])
    if tool == "ruff":
        if result.returncode not in (0, 1):
            sys.exit(f"ruff failed:\n{result.stderr}")
        return len(json.loads(result.stdout))
    # mypy: one "error:" line per error ("note:" lines are continuation).
    if result.returncode not in (0, 1):
        sys.exit(f"mypy failed:\n{result.stdout}{result.stderr}")
    return sum(1 for line in result.stdout.splitlines() if ": error:" in line)


def load_baseline() -> dict[str, dict[str, object]]:
    if not BASELINE_FILE.exists():
        return {}
    return json.loads(BASELINE_FILE.read_text())


def main(argv: list[str]) -> int:
    update = "--update" in argv
    tools = [a for a in argv if a in COMMANDS]
    if not tools:
        sys.exit(__doc__)

    baseline = load_baseline()
    failed = False
    for tool in tools:
        count = count_errors(tool)
        version = tool_version(tool)
        if update:
            baseline[tool] = {"errors": count, "version": version}
            print(f"{tool}: baseline set to {count} ({version})")
            continue

        entry = baseline.get(tool)
        if entry is None:
            print(f"{tool}: no baseline; run with --update first")
            failed = True
            continue
        allowed = int(entry["errors"])  # type: ignore[call-overload]
        if entry["version"] != version:
            print(
                f"{tool}: baseline was produced with {entry['version']} but "
                f"{version} is installed; counts are not comparable. Install "
                "the pinned version or regenerate the baseline."
            )
            failed = True
        elif count > allowed:
            print(f"{tool}: FAIL {count} errors > baseline {allowed}")
            failed = True
        elif count < allowed:
            print(
                f"{tool}: {count} errors < baseline {allowed}; lower it with "
                f"`python scripts/lint_ratchet.py {tool} --update`"
            )
        else:
            print(f"{tool}: OK ({count} errors, baseline {allowed})")

    if update:
        BASELINE_FILE.write_text(json.dumps(baseline, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
