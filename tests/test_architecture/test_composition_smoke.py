"""Composition smoke: the app still wires up, with no live services.

Import-boundary tests can't see a wrong constructor kwarg or a task that
vanished; these build the real graphs. ``GENAI_ENVIRONMENT=test`` (see
``make test-architecture``) keeps everything offline - the only I/O at
construction time is MinIO's bucket check, neutralised below.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASKS_FILE = ROOT / "src/infrastructure/entrypoint/worker/celery/tasks.py"
WORKER_FACTORIES = (
    "src.infrastructure.workflows.celery.factories",
    "src.infrastructure.workflows.celery.task_factories",
)
API_FACTORIES_DIR = ROOT / "src/infrastructure/entrypoint/api/factories"


def _factory_modules() -> list[str]:
    api = sorted(
        f"src.infrastructure.entrypoint.api.factories.{p.stem}"
        for p in API_FACTORIES_DIR.glob("*_factory.py")
    )
    return [*WORKER_FACTORIES, *api]


def _zero_arg_factories() -> list[tuple[str, str]]:
    found = []
    for module_name in _factory_modules():
        module = importlib.import_module(module_name)
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("get_") or fn.__module__ != module_name:
                continue
            required = [
                p
                for p in inspect.signature(fn).parameters.values()
                if p.default is p.empty
                and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
            ]
            if not required:
                found.append((module_name, name))
    return found


def test_api_app_builds_and_generates_openapi() -> None:
    from src.infrastructure.entrypoint.api.fastapi_app import create_app

    app = create_app()

    assert len(app.routes) > 0
    # Building the schema catches broken response_model / dependency types.
    assert app.openapi()["paths"]


def test_every_declared_celery_task_is_registered() -> None:
    declared: set[str] = set()
    for node in ast.walk(ast.parse(TASKS_FILE.read_text(encoding="utf-8"))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and getattr(deco.func, "attr", "") == "task":
                for kw in deco.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        declared.add(kw.value.value)
    assert declared, "no @app.task(name=...) found in tasks.py"

    importlib.import_module("src.infrastructure.entrypoint.worker.celery.tasks")
    from src.infrastructure.entrypoint.worker.celery.celery_app import app

    missing = sorted(declared - set(app.tasks))
    assert not missing, f"declared in tasks.py but not registered: {missing}"


@pytest.mark.parametrize(
    ("module_name", "factory_name"),
    _zero_arg_factories(),
    ids=lambda v: v.rsplit(".", 1)[-1],
)
def test_factory_builds_without_live_services(
    module_name: str, factory_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.infrastructure.persistence.object_storage.minio import (
        minio_object_storage_adapter,
    )

    monkeypatch.setattr(
        minio_object_storage_adapter.MinioObjectStorageAdapter,
        "_ensure_bucket",
        lambda self: None,
    )
    factory = getattr(importlib.import_module(module_name), factory_name)

    factory()

    # Leave no singleton behind for other tests that patch collaborators.
    clear = getattr(factory, "cache_clear", None)
    if clear is not None:
        clear()
