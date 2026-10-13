"""Architecture fitness tests, part 2: the CLAUDE.md *conventions*.

``test_import_boundaries`` covers who may import whom; this file covers the
shape rules: port shapes, factory/``lru_cache`` hygiene, orphan config
fields, fake naming + test-tree mirror, Dockerfile local/OKD parity and
lazy-import dependency coverage of the shared worker/MCP modules.

Same ratchet as the other architecture tests: ``KNOWN_VIOLATIONS`` is the
debt at the time of writing - a new violation fails, a resolved one must be
deleted from the set. Pure ``ast``/text, no services needed.

Run: ``make test-architecture``.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
PORTS = SRC / "application/ports"
REQ = ROOT / "deploy/requirements"
DOCKER = ROOT / "deploy/local/docker"

# (rule, location, detail)
KNOWN_VIOLATIONS: set[tuple[str, str, str]] = {
    # Several Protocol/ABC in one port file; split or fold into one.
    (
        "port-one-per-file",
        "src/application/ports/alert_schema_port.py",
        "3 Protocol/ABC classes",
    ),
    (
        "port-one-per-file",
        "src/application/ports/analyst_capacity_import_port.py",
        "2 Protocol/ABC classes",
    ),
    (
        "port-one-per-file",
        "src/application/ports/dataset_analysis_port.py",
        "2 Protocol/ABC classes",
    ),
    (
        "port-one-per-file",
        "src/application/ports/embedding_port.py",
        "2 Protocol/ABC classes",
    ),
    (
        "port-one-per-file",
        "src/application/ports/fraud_label_review_import_port.py",
        "2 Protocol/ABC classes",
    ),
    (
        "port-one-per-file",
        "src/application/ports/llm_unit_of_work_port.py",
        "2 Protocol/ABC classes",
    ),
    (
        "port-one-per-file",
        "src/application/ports/monitoring_port.py",
        "2 Protocol/ABC classes",
    ),
    (
        "port-one-per-file",
        "src/application/ports/research_port.py",
        "3 Protocol/ABC classes",
    ),
    (
        "port-one-per-file",
        "src/application/ports/workflow_port.py",
        "2 Protocol/ABC classes",
    ),
    # Deployment metadata label set in compose/configmaps; no code reads it.
    ("config-orphan", "src/infrastructure/core/config.py", "GENAI_APPLICATION"),
    # Fakes should be ``InMemoryX`` / ``RecordingX`` (CLAUDE.md Testing).
    (
        "fake-naming",
        "tests/test_application/test_use_cases/test_analyst_capacity/test_get_analyst_capacity_import.py",
        "StubAnalystCapacityImportStatusReader",
    ),
    (
        "fake-naming",
        "tests/test_application/test_use_cases/test_analyze_dataset_on_demand.py",
        "FakeDatasetRepository",
    ),
    (
        "fake-naming",
        "tests/test_application/test_use_cases/test_append_dataset_rows.py",
        "FakeDatasetRepository",
    ),
    (
        "fake-naming",
        "tests/test_application/test_use_cases/test_curate_alert_to_dataset.py",
        "FakeDatasetRepository",
    ),
    (
        "fake-naming",
        "tests/test_application/test_use_cases/test_generate_event_batch.py",
        "StubDatasetReaderGateway",
    ),
    (
        "fake-naming",
        "tests/test_application/test_use_cases/test_get_dataset_rows.py",
        "FakeDatasetRepository",
    ),
    (
        "fake-naming",
        "tests/test_application/test_use_cases/test_metrics_maintenance.py",
        "FakeLifecycleReader",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_alert_schema_and_raw_router.py",
        "FakeAlertRepository",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_alert_schema_and_raw_router.py",
        "FakeSchemaUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_alert_schema_and_raw_router.py",
        "FakeStorage",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_async_operations_router.py",
        "FakeGetAsyncOperationUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_async_operations_router.py",
        "FakeReconcileAsyncOperationsUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_configurations_test_router.py",
        "FakePreviewConfigurationUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_metrics_query_cache.py",
        "FakeMonotonic",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_metrics_query_cache.py",
        "FakeOutput",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_scenarios_router.py",
        "FakeCreateUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_scenarios_router.py",
        "FakeDeleteUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_scenarios_router.py",
        "FakeGenerateBatchUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_scenarios_router.py",
        "FakeGetUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_scenarios_router.py",
        "FakeLifecycleUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_scenarios_router.py",
        "FakeListUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_scenarios_router.py",
        "FakeStatusUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_scenarios_router.py",
        "FakeUpdateUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_entrypoint/test_simulator_tick_task.py",
        "StubGenerateEventBatchUseCase",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_workflows/test_alert_review_workflow.py",
        "FakeLLMUnitOfWork",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_workflows/test_alert_review_workflow.py",
        "FakeLLMUnitOfWorkFactory",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_workflows/test_model_history_evaluation.py",
        "FakeDatasets",
    ),
    (
        "fake-naming",
        "tests/test_infrastructure/test_workflows/test_model_history_evaluation.py",
        "FakeModels",
    ),
    # Local compose healthcheck shells out to curl; OKD uses cluster probes.
    (
        "dockerfile-parity",
        "Dockerfile.api <-> Dockerfile.api.okd",
        "apt: curl only in Dockerfile.api",
    ),
}


def _py_files(base: Path):
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _check(rule: str, found: set[tuple[str, str, str]]) -> None:
    known = {v for v in KNOWN_VIOLATIONS if v[0] == rule}
    new = sorted(found - known)
    fixed = sorted(known - found)
    msg = []
    if new:
        msg.append(
            f"[{rule}] NEW violations (fix them, don't baseline):\n  "
            + "\n  ".join(f"{loc}: {d}" for _, loc, d in new)
        )
    if fixed:
        msg.append(
            f"[{rule}] resolved - remove from KNOWN_VIOLATIONS:\n  "
            + "\n  ".join(f"{loc}: {d}" for _, loc, d in fixed)
        )
    assert not msg, "\n".join(msg)


def _base_names(cls: ast.ClassDef) -> set[str]:
    names = set()
    for b in cls.bases:
        node = b.value if isinstance(b, ast.Subscript) else b  # Protocol[T]
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _decorator_names(fn: ast.AST) -> set[str]:
    names = set()
    for d in getattr(fn, "decorator_list", []):
        node = d.func if isinstance(d, ast.Call) else d
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


# --------------------------------------------------------------------- ports

_PORT_BASES = {"Protocol", "ABC"}
_VALUE_BASES = {
    "Enum",
    "StrEnum",
    "IntEnum",
    "Flag",
    "str",
    "int",
    "NamedTuple",
    "TypedDict",
    "Exception",
    "ValueError",
    "RuntimeError",
    "KeyError",
    "LookupError",
    "TypeError",
}


def test_ports_are_protocol_abc_or_value_objects() -> None:
    """CLAUDE.md "Port shapes": a port file holds dataclass records, enums
    and the Protocol/ABC - no other kind of class, no ``models`` module."""
    found: set[tuple[str, str, str]] = set()
    for path in sorted(PORTS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        if path.stem.startswith(("models", "records", "schemas")):
            found.add(("port-shape", _rel(path), "separate models module"))
        tree = _tree(path)
        defined = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
        ports = 0
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _base_names(node)
            is_dataclass = "dataclass" in _decorator_names(node)
            is_port = bool(bases & _PORT_BASES)
            ports += is_port
            if is_dataclass or is_port or bases & _VALUE_BASES or bases & defined:
                continue
            if any(b.endswith(("Error", "Exception")) for b in bases):
                continue
            found.add(
                (
                    "port-shape",
                    _rel(path),
                    f"class {node.name} is neither "
                    "dataclass/enum/exception nor Protocol/ABC",
                )
            )
        if ports > 1:
            found.add(
                ("port-one-per-file", _rel(path), f"{ports} Protocol/ABC classes")
            )
    _check("port-shape", {v for v in found if v[0] == "port-shape"})
    _check("port-one-per-file", {v for v in found if v[0] == "port-one-per-file"})


# ----------------------------------------------------------------- factories

_FACTORY_FILES = [
    *sorted((SRC / "infrastructure/entrypoint/api/factories").glob("*.py")),
    SRC / "infrastructure/workflows/celery/factories.py",
    SRC / "infrastructure/workflows/celery/task_factories.py",
    SRC / "infrastructure/entrypoint/mcp/factories.py",
    SRC / "infrastructure/entrypoint/simulator/celery/factories.py",
]
_FACTORY_FILES = [p for p in _FACTORY_FILES if p.is_file() and p.name != "__init__.py"]
_ADAPTER_PREFIXES = ("Dynamo", "Minio", "OpenSearch", "OpenTelemetry", "Langchain")
_CACHE_DECOS = {"lru_cache", "cache"}


def _get_functions(path: Path):
    for node in _tree(path).body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("get_"):
            yield node


def _required_params(fn: ast.FunctionDef) -> int:
    a = fn.args
    positional = len(a.posonlyargs) + len(a.args) - len(a.defaults)
    kwonly = sum(1 for d in a.kw_defaults if d is None)
    return positional + kwonly


def _returned_names(fn: ast.FunctionDef) -> set[str]:
    """Names in the return annotation plus the callee of ``return X(...)``."""
    names: set[str] = set()
    if fn.returns is not None:
        for n in ast.walk(fn.returns):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Attribute):
                names.add(n.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                names.add(n.value)
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Call):
            f = n.value.func
            names.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return names


def test_stateless_adapter_factories_are_cached() -> None:
    """CLAUDE.md DI: zero-arg ``get_*`` returning an infra adapter is a
    ``@lru_cache`` singleton (``get_model_repository`` once missed it)."""
    found: set[tuple[str, str, str]] = set()
    for path in _FACTORY_FILES:
        for fn in _get_functions(path):
            if _required_params(fn):
                continue
            if not any(n.startswith(_ADAPTER_PREFIXES) for n in _returned_names(fn)):
                continue
            if not _decorator_names(fn) & _CACHE_DECOS:
                found.add(("factory-cached", _rel(path), fn.name))
    _check("factory-cached", found)


def test_one_factory_per_adapter_within_a_factory_module() -> None:
    """CLAUDE.md "one factory function per port per adapter choice": inside
    one module two cached (singleton) ``get_*`` must not return the same
    type. (API vs worker vs MCP duplicates are by design - separate Poetry
    projects; uncached use-case factories legitimately share a wrapper.)"""
    found: set[tuple[str, str, str]] = set()
    for path in _FACTORY_FILES:
        seen: dict[str, str] = {}
        for fn in _get_functions(path):
            if (
                _required_params(fn)
                or fn.returns is None
                or not _decorator_names(fn) & _CACHE_DECOS
            ):
                continue
            ret = ast.unparse(fn.returns)
            if ret in {"None", "bool", "str", "int", "float", "dict", "list"}:
                continue
            if ret in seen:
                found.add(
                    (
                        "factory-duplicate",
                        _rel(path),
                        f"{seen[ret]} and {fn.name} both return {ret}",
                    )
                )
            else:
                seen[ret] = fn.name
    _check("factory-duplicate", found)


# -------------------------------------------------------------------- config


def test_every_config_field_is_read_somewhere() -> None:
    config_path = SRC / "infrastructure/core/config.py"
    cls = next(
        n
        for n in _tree(config_path).body
        if isinstance(n, ast.ClassDef) and n.name == "Config"
    )
    fields = {
        n.target.id
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    used: set[str] = set()
    # ``config/<env>/gunicorn.conf.py`` reads GENAI_* / logging level too.
    for path in [*_py_files(SRC), *_py_files(ROOT / "config")]:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Attribute) and node.attr in fields:
                used.add(node.attr)
            elif isinstance(node, ast.Constant) and node.value in fields:
                # getattr(cfg, "X") / model_dump().get("X") style reads.
                used.add(node.value)
    found = {("config-orphan", _rel(config_path), f) for f in fields - used}
    _check("config-orphan", found)


# --------------------------------------------------------------------- tests

_FAKE_BAD_AFFIX = re.compile(r"^(Fake|Stub|Mock|Dummy|Spy)|(Fake|Stub|Mock|Dummy|Spy)$")


def test_fakes_are_named_inmemory_or_recording() -> None:
    found: set[tuple[str, str, str]] = set()
    for path in _py_files(TESTS):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ClassDef) and _FAKE_BAD_AFFIX.search(node.name):
                found.add(("fake-naming", _rel(path), node.name))
    _check("fake-naming", found)


def _mirror_dir(rel_dir: Path, src_base: Path) -> bool:
    """``test_a/test_b`` mirrors ``a/b`` (CLAUDE.md "test tree mirrors src")."""
    parts = [p.removeprefix("test_") for p in rel_dir.parts]
    return (src_base.joinpath(*parts)).is_dir()


def test_test_tree_mirrors_src_tree() -> None:
    """Test sub-folders must map to a real ``src`` folder: use-case tests
    under ``test_use_cases/test_<sub>`` <-> ``application/use_cases/<sub>``,
    infrastructure tests under ``test_<domain>`` <-> ``infrastructure/<domain>``.
    Flat files at the root of ``test_use_cases`` are allowed."""
    found: set[tuple[str, str, str]] = set()
    pairs = [
        (TESTS / "test_application/test_use_cases", SRC / "application/use_cases"),
        (TESTS / "test_infrastructure", SRC / "infrastructure"),
    ]
    for test_root, src_base in pairs:
        for d in sorted(
            p
            for p in test_root.rglob("*")
            if p.is_dir() and "__pycache__" not in p.parts
        ):
            if not any(d.glob("*.py")):
                continue
            rel_dir = d.relative_to(test_root)
            if not _mirror_dir(rel_dir, src_base):
                found.add(
                    (
                        "test-mirror",
                        _rel(d),
                        f"no matching folder under {_rel(src_base)}",
                    )
                )
    _check("test-mirror", found)


# --------------------------------------------------------------- Dockerfiles

_DOCKER_PAIRS = [
    ("Dockerfile.api", "Dockerfile.api.okd"),
    ("Dockerfile.worker", "Dockerfile.worker.okd"),
    ("Dockerfile.mcp", "Dockerfile.mcp.okd"),
    ("Dockerfile.simulator.worker", "Dockerfile.simulator.worker.okd"),
]


def _docker_facts(path: Path) -> dict[str, set[str]]:
    """Statements that must match between the local and OKD variants."""
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    facts: dict[str, set[str]] = {
        "apt": set(),
        "expose": set(),
        "cmd": set(),
        "user": set(),
    }
    for raw in text.splitlines():
        line = " ".join(raw.split())
        up = line.upper()
        if up.startswith("EXPOSE "):
            facts["expose"].update(line.split()[1:])
        elif up.startswith(("CMD ", "ENTRYPOINT ")):
            facts["cmd"].add(line)
        elif up.startswith("USER "):
            facts["user"].add(line)
        for m in re.finditer(r"apt-get install\b([^&;|]*)", line):
            facts["apt"].update(
                t
                for t in m.group(1).split()
                if not t.startswith("-") and not t.startswith("$")
            )
    return facts


def test_local_and_okd_dockerfiles_agree_on_runtime_facts() -> None:
    found: set[tuple[str, str, str]] = set()
    for local, okd in _DOCKER_PAIRS:
        a, b = _docker_facts(DOCKER / local), _docker_facts(DOCKER / okd)
        for kind in a:
            for item in sorted(a[kind] ^ b[kind]):
                side = local if item in a[kind] else okd
                found.add(
                    (
                        "dockerfile-parity",
                        f"{local} <-> {okd}",
                        f"{kind}: {item} only in {side}",
                    )
                )
    _check("dockerfile-parity", found)


# ------------------------------------------------ shared-module dependencies

_SHARED_MODULES = [
    "src/infrastructure/workflows/celery/model_training.py",
    "src/infrastructure/entrypoint/mcp/scoring.py",
]
_SHARED_PYPROJECTS = ["pyproject.worker.toml", "pyproject.mcp.toml"]
_ML_PACKAGES = {"pandas", "numpy", "xgboost", "sklearn", "joblib", "scipy"}
_IMPORT_TO_DIST = {"sklearn": "scikit-learn"}


def _declared_names(pyproject: str) -> set[str]:
    data = tomllib.loads((REQ / pyproject).read_text(encoding="utf-8"))
    return {
        re.sub(r"[-_.]+", "-", d).lower()
        for d in data["tool"]["poetry"]["dependencies"]
    }


def test_shared_ml_modules_declare_lazy_imports_in_worker_and_mcp() -> None:
    """The feature-building code is shared by worker and MCP; a lazy
    ``import pandas`` inside a function never shows at container start, so
    the load-time dependency test can't see it. Check *every* import."""
    found: set[tuple[str, str, str]] = set()
    for rel in _SHARED_MODULES:
        path = ROOT / rel
        if not path.is_file():
            continue
        tops: set[str] = set()
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                tops.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                tops.add(node.module.split(".")[0])
        for pkg in sorted(tops & _ML_PACKAGES):
            dist = _IMPORT_TO_DIST.get(pkg, pkg)
            for pyproject in _SHARED_PYPROJECTS:
                if dist not in _declared_names(pyproject):
                    found.add(("shared-ml-deps", rel, f"{pkg} missing in {pyproject}"))
    _check("shared-ml-deps", found)
