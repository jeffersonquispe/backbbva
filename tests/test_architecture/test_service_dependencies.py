"""Each service must declare every third-party package it imports at load.

CLAUDE.md: the API, worker, MCP and simulator are separate Poetry projects
with separate lock files; a module-level import of a package that is only in
another project's pyproject is an ``ImportError`` at container start.

For each service entry module this computes the *import-time* closure inside
``src`` (module-level statements only - imports nested in functions are the
repo's deliberate lazy-import pattern and don't run at load) and checks every
third-party top-level package against that service's pyproject, plus the
transitive requirements of the declared packages (via installed metadata).

Ratchet like ``test_import_boundaries``: ``KNOWN_GAPS`` is the debt at the
time of writing; new gaps fail, fixed ones must be removed.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from functools import cache
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
REQ = ROOT / "deploy/requirements"

# service -> (pyproject, entry modules that run at container start)
SERVICES: dict[str, tuple[str, list[str]]] = {
    "api": ("pyproject.toml", ["src.infrastructure.entrypoint.api.fastapi_app"]),
    "worker": (
        "pyproject.worker.toml",
        [
            "src.infrastructure.entrypoint.worker.celery.celery_app",
            "src.infrastructure.entrypoint.worker.celery.tasks",
        ],
    ),
    "mcp": ("pyproject.mcp.toml", ["src.infrastructure.entrypoint.mcp.server"]),
    "simulator": (
        "pyproject.simulator.toml",
        ["src.infrastructure.entrypoint.simulator.celery.celery_app"],
    ),
}

# (service, import name) pairs that are known to be missing today.
KNOWN_GAPS: set[tuple[str, str]] = set()

_STDLIB = set(sys.stdlib_module_names)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _module_path(module: str) -> Path | None:
    base = ROOT.joinpath(*module.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def _module_level_nodes(tree: ast.AST):
    """Yield statements executed at import, not descending into defs."""
    stack = list(getattr(tree, "body", []))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        for field in ("body", "orelse", "finalbody", "handlers"):
            stack.extend(getattr(node, field, []) or [])


def _scan(module: str, seen_src: set[str], third_party: dict[str, str]) -> None:
    if module in seen_src:
        return
    path = _module_path(module)
    if path is None:
        return
    seen_src.add(module)
    # importing a.b.c executes a/__init__ and a/b/__init__ first
    parts = module.split(".")
    for i in range(1, len(parts)):
        _scan(".".join(parts[:i]), seen_src, third_party)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in _module_level_nodes(tree):
        targets: list[str] = []
        if isinstance(node, ast.Import):
            targets = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            targets = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for target in targets:
            top = target.split(".")[0]
            if top == "src":
                _scan(target, seen_src, third_party)
            elif top not in _STDLIB and top != "__future__":
                third_party.setdefault(top, f"{module} -> {target}")


def _closure(entries: list[str]) -> dict[str, str]:
    third_party: dict[str, str] = {}
    seen: set[str] = set()
    for entry in entries:
        _scan(entry, seen, third_party)
    return third_party


@cache
def _declared(pyproject: str) -> set[str]:
    data = tomllib.loads((REQ / pyproject).read_text(encoding="utf-8"))
    deps = data["tool"]["poetry"]["dependencies"]
    allowed: set[str] = set()
    pending = [_norm(d) for d in deps if d != "python"]
    while pending:
        dist = pending.pop()
        if dist in allowed:
            continue
        allowed.add(dist)
        try:
            for req in metadata.requires(dist) or []:
                if "extra ==" in req:
                    continue
                pending.append(_norm(re.split(r"[ ;<>=!~\[(]", req, maxsplit=1)[0]))
        except metadata.PackageNotFoundError:
            continue
    return allowed


@cache
def _import_to_dists() -> dict[str, set[str]]:
    return {
        k: {_norm(d) for d in v} for k, v in metadata.packages_distributions().items()
    }


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_service_declares_every_module_level_third_party_import(service: str) -> None:
    pyproject, entries = SERVICES[service]
    declared = _declared(pyproject)
    mapping = _import_to_dists()
    missing: dict[str, str] = {}
    for name, via in _closure(entries).items():
        dists = mapping.get(name)
        if dists is None:
            # Not installed here: can't prove it either way - compare by name.
            dists = {_norm(name)}
        if not dists & declared:
            missing[name] = via
    found = {(service, name) for name in missing}
    known = {g for g in KNOWN_GAPS if g[0] == service}
    new = sorted(found - known)
    fixed = sorted(known - found)
    problems = []
    if new:
        problems.append(
            f"[{service}] imported at load but not in {pyproject}:\n  "
            + "\n  ".join(f"{n}  (first via {missing[n]})" for _, n in new)
        )
    if fixed:
        problems.append(
            f"[{service}] resolved - remove from KNOWN_GAPS:\n  "
            + "\n  ".join(n for _, n in fixed)
        )
    assert not problems, "\n".join(problems)
