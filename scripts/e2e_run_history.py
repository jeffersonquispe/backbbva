"""Shared local history and freshness checks for Playwright E2E runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "frontend_mockup"
HISTORY = Path(os.getenv("ARIA_E2E_HISTORY", "/tmp/aria-e2e-history.jsonl"))
RUNS_DIR = Path(os.getenv("ARIA_E2E_RUNS_DIR", "/tmp/aria-e2e-runs"))


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout


def _repo_fingerprint(repo: Path) -> str:
    digest = hashlib.sha256()
    digest.update(_git(repo, "rev-parse", "HEAD"))
    digest.update(_git(repo, "diff", "HEAD", "--binary"))
    status = _git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    digest.update(status)
    for entry in status.split(b"\0"):
        if not entry:
            continue
        path = entry[3:].decode(errors="surrogateescape")
        candidate = repo / path
        if candidate.is_file() and not candidate.is_symlink():
            digest.update(path.encode(errors="surrogateescape"))
            digest.update(candidate.read_bytes())
    return digest.hexdigest()


def _repo_snapshot(repo: Path) -> dict[str, object]:
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    status = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    changed: list[dict[str, object]] = []
    for entry in status.split(b"\0"):
        if not entry:
            continue
        state = entry[:2].decode(errors="replace")
        relative_path = entry[3:].decode(errors="surrogateescape")
        path = repo / relative_path
        item: dict[str, object] = {"path": relative_path, "git_status": state}
        if path.is_file() and not path.is_symlink():
            stat = path.stat()
            item.update(
                {
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, UTC
                    ).isoformat(),
                    "size_bytes": stat.st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        changed.append(item)
    latest_commit = _git(repo, "show", "-s", "--format=%cI", "HEAD").decode().strip()
    commit_files = [
        line
        for line in _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        .decode(errors="replace")
        .splitlines()
        if line
    ]
    return {
        "root": str(repo),
        "branch": _git(repo, "branch", "--show-current").decode().strip(),
        "head_commit": head,
        "head_commit_at": latest_commit,
        "head_commit_files": commit_files,
        "working_tree_clean": not changed,
        "changed_files": changed,
        "status_porcelain": status.decode(errors="surrogateescape").replace("\0", "\\0"),
    }


def workspace_snapshot() -> dict[str, object]:
    captured_at = datetime.now(UTC).isoformat()
    repositories = {"backend": _repo_snapshot(ROOT), "frontend": _repo_snapshot(FRONTEND)}
    state_fingerprint = fingerprint("workspace-snapshot", "")
    return {
        "captured_at": captured_at,
        "fingerprint": state_fingerprint,
        "repositories": repositories,
    }


def fingerprint(label: str, specs: str) -> str:
    payload = {
        "label": label,
        "specs": " ".join(specs.split()),
        "backend": _repo_fingerprint(ROOT),
        "frontend": _repo_fingerprint(FRONTEND),
        "run_settings": {
            key: os.getenv(key, "")
            for key in (
                "E2E_PLAYWRIGHT_WORKERS",
                "E2E_LOCAL_API_WORKERS",
                "LOCAL_DOCKER_TEST_WORKERS",
                "LOCAL_DOCKER_PROJECT",
                "LOCAL_DOCKER_ENV",
                "E2E_BASE_URL",
            )
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _entries() -> list[dict[str, object]]:
    if not HISTORY.exists():
        return []
    entries: list[dict[str, object]] = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _latest_success(label: str, digest: str) -> dict[str, object] | None:
    max_age_hours = max(0.0, float(os.getenv("E2E_REUSE_MAX_AGE_HOURS", "24")))
    now = datetime.now(UTC)
    for entry in reversed(_entries()):
        if (
            entry.get("label") != label
            or entry.get("fingerprint") != digest
            or entry.get("status") != "passed"
        ):
            continue
        try:
            finished = datetime.fromisoformat(str(entry["finished_at"]))
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=UTC)
        except (KeyError, ValueError):
            continue
        if (now - finished).total_seconds() <= max_age_hours * 3600:
            return entry
    return None


def _record(entry: dict[str, object]) -> None:
    HISTORY.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    HISTORY.chmod(0o600)


def run(
    label: str, specs: str, command: list[str], env: dict[str, str] | None = None
) -> int:
    digest = fingerprint(label, specs)
    start_snapshot = workspace_snapshot()
    start_snapshot["fingerprint"] = digest
    previous = _latest_success(label, digest)
    if previous and os.getenv("E2E_FORCE_RUN") != "1":
        print(
            f"E2E omitido: {label} ya pasó el {previous.get('finished_at')} "
            "con el mismo fingerprint. Usa E2E_FORCE_RUN=1 para repetir."
        )
        _record(
            {
                "run_id": str(uuid.uuid4()),
                "label": label,
                "specs": specs,
                "fingerprint": digest,
                "status": "reused",
                "workspace_snapshot": start_snapshot,
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "reused_run_id": previous.get("run_id"),
            }
        )
        return 0

    run_id = str(uuid.uuid4())
    started = datetime.now(UTC).isoformat()
    start_time = time.monotonic()
    output: list[str] = []
    process = subprocess.Popen(
        command,
        cwd=FRONTEND,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        output.append(line)
    return_code = process.wait()
    status = "passed" if return_code == 0 else "failed"
    finished = datetime.now(UTC).isoformat()
    end_snapshot = workspace_snapshot()
    RUNS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUNS_DIR.chmod(0o700)
    log_path = RUNS_DIR / f"{run_id}.log"
    log_path.write_text(
        f"label: {label}\nspecs: {specs}\nstatus: {status}\n"
        f"command: {shlex.join(command)}\nexit_code: {return_code}\n"
        f"started_at: {started}\nfinished_at: {finished}\n"
        f"duration_seconds: {time.monotonic() - start_time:.2f}\n\n"
        + "".join(output),
        encoding="utf-8",
    )
    log_path.chmod(0o600)
    _record(
        {
            "run_id": run_id,
            "label": label,
            "specs": specs,
            "fingerprint": digest,
            "status": status,
            "exit_code": return_code,
            "started_at": started,
            "finished_at": finished,
            "duration_seconds": round(time.monotonic() - start_time, 2),
            "log": str(log_path),
            "workspace_snapshot": start_snapshot,
            "finish_workspace_snapshot": end_snapshot,
        }
    )
    return return_code


def environment_status() -> int:
    current = workspace_snapshot()
    current_fingerprint = fingerprint("local-environment", "compose")
    entries = [entry for entry in _entries() if entry.get("event") == "environment_started"]
    print(f"Estado de código actual: {current_fingerprint}")
    _print_repository_snapshot("estado actual", current)
    if not entries:
        print("No hay lanzamientos de entorno local registrados todavía.")
        return 0
    previous = entries[-1]
    snapshot = previous.get("workspace_snapshot", {})
    print(
        f"Último lanzamiento registrado: {previous.get('finished_at')} "
        f"(run_id={previous.get('run_id')})"
    )
    print(f"Fingerprint lanzado: {previous.get('fingerprint')}")
    _print_repository_snapshot("estado al lanzar", snapshot)
    if previous.get("fingerprint") == current_fingerprint:
        print("El código/configuración Git coincide con el último lanzamiento registrado.")
    else:
        print("El estado del código cambió desde el último lanzamiento registrado.")
        old_repositories = snapshot.get("repositories", {}) if isinstance(snapshot, dict) else {}
        for name, repo in (("backend", ROOT), ("frontend", FRONTEND)):
            old = old_repositories.get(name, {}) if isinstance(old_repositories, dict) else {}
            old_head = old.get("head_commit") if isinstance(old, dict) else None
            current_head = _git(repo, "rev-parse", "HEAD").decode().strip()
            if old_head and old_head != current_head:
                changed_since = _git(repo, "diff", "--name-status", f"{old_head}..{current_head}")
                for line in changed_since.decode(errors="replace").splitlines():
                    print(f"  {name}: {line}")
            for item in _repo_snapshot(repo)["changed_files"]:
                if isinstance(item, dict):
                    print(f"  {name}: {item.get('git_status')} {item.get('path')}")
    return 0


def _print_repository_snapshot(label: str, snapshot: object) -> None:
    if not isinstance(snapshot, dict):
        return
    repositories = snapshot.get("repositories", {})
    if not isinstance(repositories, dict):
        return
    for name in ("backend", "frontend"):
        repo = repositories.get(name)
        if not isinstance(repo, dict):
            continue
        print(
            f"  {label} {name}: branch={repo.get('branch') or '(detached)'} "
            f"HEAD={repo.get('head_commit')} commit_at={repo.get('head_commit_at')} "
            f"clean={repo.get('working_tree_clean')}"
        )
        for item in repo.get("changed_files", []):
            if isinstance(item, dict):
                print(
                    f"    {item.get('git_status')} {item.get('path')} "
                    f"modified_at={item.get('modified_at', 'n/a')} "
                    f"sha256={item.get('sha256', 'n/a')}"
                )


def record_environment_launch() -> int:
    snapshot = workspace_snapshot()
    _record(
        {
            "run_id": str(uuid.uuid4()),
            "event": "environment_started",
            "label": "local-environment",
            "specs": "compose stack + frontend",
            "fingerprint": fingerprint("local-environment", "compose"),
            "status": "started",
            "started_at": snapshot["captured_at"],
            "finished_at": snapshot["captured_at"],
            "workspace_snapshot": snapshot,
        }
    )
    print(f"Lanzamiento de entorno local registrado en {HISTORY}")
    return 0


def show_history(limit: int) -> int:
    entries = _entries()[-limit:]
    if not entries:
        print(f"No hay corridas registradas en {HISTORY}")
        return 0
    print(f"Historial E2E: {HISTORY}")
    for entry in reversed(entries):
        print(
            f"{entry.get('finished_at', '?')}  {str(entry.get('status', '?')).upper():7} "
            f"{entry.get('label', '?')}  {entry.get('duration_seconds', '-')}s"
        )
        if entry.get("status") == "reused":
            print(f"  resultado reutilizado de run_id={entry.get('reused_run_id')}")
        if entry.get("log"):
            print(f"  log: {entry['log']}")
        print(f"  specs: {entry.get('specs', '')}")
        snapshot = entry.get("workspace_snapshot")
        if isinstance(snapshot, dict):
            repositories = snapshot.get("repositories", {})
            if isinstance(repositories, dict):
                for name in ("backend", "frontend"):
                    repo = repositories.get(name)
                    if isinstance(repo, dict):
                        changed = repo.get("changed_files", [])
                        print(
                            f"  {name}: {repo.get('branch') or '(detached)'}@"
                            f"{str(repo.get('head_commit', ''))[:12]} "
                            f"dirty_files={len(changed) if isinstance(changed, list) else '?'}"
                        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", help="Nombre de la suite")
    parser.add_argument("--specs", default="", help="Specs incluidos en la suite")
    parser.add_argument("--history", action="store_true", help="Mostrar corridas recientes")
    parser.add_argument("--environment-status", action="store_true", help="Comparar el workspace con el último lanzamiento local")
    parser.add_argument("--record-environment-launch", action="store_true", help="Registrar el workspace tras iniciar el stack local")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.history:
        return show_history(max(1, args.limit))
    if args.environment_status:
        return environment_status()
    if args.record_environment_launch:
        return record_environment_launch()
    if not args.label or not args.command:
        parser.error("--label y un comando son requeridos para ejecutar una suite")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return run(args.label, args.specs, command)


if __name__ == "__main__":
    sys.exit(main())
