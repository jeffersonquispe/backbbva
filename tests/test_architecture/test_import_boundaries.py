"""Architecture fitness tests: the CLAUDE.md rules, enforced on the AST.

Ratchet: ``KNOWN_VIOLATIONS`` is the debt that existed when this file was
written. A violation not listed fails the test (no new debt); a listed one
that no longer occurs also fails (delete it from the set - debt only goes
down). Pure ``ast``, no new dependency; imports nested in functions count.

Run: ``make test-architecture``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TESTS = ROOT / "tests"

# (rule, file, module) triples; module is the offending import (or
# "os.environ" for the env-var rule).
KNOWN_VIOLATIONS: set[tuple[str, str, str]] = {
    # Wipes DynamoDB tables straight from the router; move into a port +
    # adapter + use case (E2EStateCleaner) like the other routers.
    ("router-no-adapters", "src/infrastructure/entrypoint/api/routers/e2e_router.py", "src.infrastructure.persistence"),
}

_HEAVY = {
    "fastapi", "starlette", "boto3", "botocore", "celery", "opensearchpy",
    "langchain", "langchain_core", "langchain_openai", "opentelemetry",
    "pandas", "numpy", "openpyxl", "xgboost", "sklearn", "joblib",
}
# CLAUDE.md "Observability - OTLP is the only contract".
_OBS_BACKENDS = {"phoenix", "langfuse", "langsmith", "prometheus_client", "loki", "grafana", "tempo"}
_STDLIB = set(sys.stdlib_module_names)


def _py_files(base: Path):
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _imports(path: Path) -> list[str]:
    """Absolute module names imported anywhere in the file (incl. lazy)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _check(rule: str, found: set[tuple[str, str, str]]) -> None:
    known = {v for v in KNOWN_VIOLATIONS if v[0] == rule}
    new = sorted(found - known)
    fixed = sorted(known - found)
    msg = []
    if new:
        msg.append(f"[{rule}] NEW violations (fix them, don't baseline):\n  "
                   + "\n  ".join(f"{f}: {m}" for _, f, m in new))
    if fixed:
        msg.append(f"[{rule}] resolved - remove from KNOWN_VIOLATIONS:\n  "
                   + "\n  ".join(f"{f}: {m}" for _, f, m in fixed))
    assert not msg, "\n".join(msg)


def _violations(rule: str, base: Path, banned) -> set[tuple[str, str, str]]:
    out = set()
    for path in _py_files(base):
        for mod in _imports(path):
            hit = banned(mod)
            if hit:
                out.add((rule, _rel(path), hit))
    return out


def _top(mod: str) -> str:
    return mod.split(".")[0]


def test_domain_is_framework_free() -> None:
    def banned(mod: str):
        top = _top(mod)
        if top in _STDLIB or top == "__future__" or mod.startswith("src.domain"):
            return None
        return top

    _check("domain-framework-free", _violations("domain-framework-free", SRC / "domain", banned))


def test_application_does_not_import_infrastructure() -> None:
    def banned(mod: str):
        return "src.infrastructure" if mod.startswith("src.infrastructure") else None

    _check("application-no-infra", _violations("application-no-infra", SRC / "application", banned))


def test_application_and_domain_avoid_framework_and_heavy_libs() -> None:
    def banned(mod: str):
        return _top(mod) if _top(mod) in _HEAVY else None

    found = _violations("application-no-heavy-libs", SRC / "application", banned)
    # domain's own rule already reports its third-party imports.
    _check("application-no-heavy-libs", found)


def test_domain_does_not_import_application_or_infrastructure() -> None:
    def banned(mod: str):
        return mod if mod.startswith(("src.application", "src.infrastructure")) else None

    _check("domain-inward-only", _violations("domain-inward-only", SRC / "domain", banned))


def test_no_observability_backend_imports() -> None:
    def banned(mod: str):
        return _top(mod) if _top(mod) in _OBS_BACKENDS else None

    _check("otlp-only", _violations("otlp-only", SRC, banned))


def test_env_vars_are_read_only_in_core_config() -> None:
    config = (SRC / "infrastructure/core/config.py").resolve()
    found: set[tuple[str, str, str]] = set()
    for path in _py_files(SRC):
        if path.resolve() == config:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # os.environ.pop/del mutate the process env (the simulator Celery
        # app must hide generic broker vars); only *reads* are config.
        mutating = {
            id(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr in {"pop", "setdefault", "update"}
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "os" and node.attr in {"environ", "getenv"} \
                    and id(node) not in mutating:
                found.add(("env-only-in-config", _rel(path), "os.environ"))
    _check("env-only-in-config", found)


def test_routers_do_not_build_persistence_adapters() -> None:
    """Routers get adapters through factories + Depends (CLAUDE.md DI)."""

    def banned(mod: str):
        return "src.infrastructure.persistence" if mod.startswith("src.infrastructure.persistence") else None

    base = SRC / "infrastructure/entrypoint/api/routers"
    _check("router-no-adapters", _violations("router-no-adapters", base, banned))


_WIRING_FILES = (
    "src/infrastructure/entrypoint/worker/celery/tasks.py",
    "src/infrastructure/workflows/celery/alert_review_workflow.py",
)
_WIRING_PREFIXES = ("Dynamo", "Minio", "OpenSearch", "Celery", "Mock", "Bounded", "TimeBounded")
_WIRING_SUFFIXES = ("UseCase", "Loader", "Agent", "Repository", "Adapter", "Dispatcher")


def test_worker_wiring_goes_through_celery_factories() -> None:
    """CLAUDE.md DI: tasks and the workflow runner call ``get_*`` factories
    from ``workflows/celery/factories.py``; they never build adapters or
    use cases inline."""
    found: set[tuple[str, str, str]] = set()
    for rel in _WIRING_FILES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name.startswith(_WIRING_PREFIXES) or name.endswith(_WIRING_SUFFIXES):
                found.add(("worker-wiring-in-factories", rel, name))
    _check("worker-wiring-in-factories", found)


def test_tests_use_hand_written_fakes_not_unittest_mock() -> None:
    def banned(mod: str):
        return "unittest.mock" if mod.startswith(("unittest.mock", "mock")) and _top(mod) in {"unittest", "mock"} else None

    _check("no-unittest-mock", _violations("no-unittest-mock", TESTS, banned))


def test_no_shared_conftest_under_tests() -> None:
    assert not list(TESTS.rglob("conftest.py")), "CLAUDE.md: no shared conftest.py"


def test_no_duplicate_singular_queue_dir() -> None:
    assert not [p for p in SRC.rglob("queue") if p.is_dir()], "use queues/, not queue/"
