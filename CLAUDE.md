# aria-api — architecture guide for Claude

API for the massive fraud agent for BBVA. Hexagonal / clean architecture.
Read this before adding files — most "new" needs already have a home and a
pattern to copy.

## Layers

```
src/
  domain/                 # framework-free entities/exceptions
  application/
    ports/                # contracts: Protocol or ABC, zero infra imports
    dtos/                 # per-use-case Input/Output dataclasses
    use_cases/             # one class per use case, orchestrates via ports only
  infrastructure/
    entrypoint/api/        # FastAPI routers + factories (DI)
    persistence/database/dynamodb/  # repository implementations
    queues/celery/          # Celery app + tasks
    workflows/celery/       # workflow runner (currently placeholder steps)
    monitoring/opentelemetry/  # MonitoringPort adapter
    llm/langchain/           # LLMUnitOfWorkFactory adapter
    core/config.py          # pydantic-settings Config, single source for env vars
```

**Rule: `application/` never imports from `infrastructure/`.** Use cases take
ports (interfaces) in their constructor; concrete adapters are wired in
`infrastructure/entrypoint/api/factories/` (API) or inline in Celery tasks
(worker — see below).

## Port shapes — pick the one that fits

Two established shapes, don't invent a third:

1. **Flat CRUD repo** → `Protocol` with `create`/`get`/`update`/`list`.
   Examples: `alert_port.py`, `workflow_port.py`, `audit_port.py`.
2. **Single-behavior abstraction** → `ABC` with `raise NotImplementedError`
   (or `@abstractmethod`), one primary method, swappable backend.
   Examples: `workflow_executor_port.py` (`WorkflowExecutor.start`),
   `async_execution_inspector_port.py` (`AsyncExecutionInspector.inspect`),
   `monitoring_port.py` (`MonitoringPort.start`),
   `llm_unit_of_work_port.py` (`LLMUnitOfWorkFactory.create`).

Every port file is self-contained: dataclass records + enum(s) + the
Protocol/ABC, all in one file. No separate "models" module.

## Adding a new adapter for an existing port

Don't touch `application/`. Add a new subclass under `infrastructure/`,
named by domain then tech, e.g. `infrastructure/<domain>/<tech>/`:

```
infrastructure/monitoring/opentelemetry/   ← OpenTelemetryMonitoring(MonitoringPort)
infrastructure/llm/langchain/               ← LangchainAzureLLMUnitOfWorkFactory(LLMUnitOfWorkFactory)
infrastructure/queues/celery/                ← Celery executor/inspector adapters
```

Selection between adapters is a plain factory function with an env-var
switch — see `async_operation_factory.py`'s `ASYNC_EXECUTOR_BACKEND` branch
for the template.

## DI / wiring conventions

- Factory **functions**, not classes/containers.
- Stateless adapters (repos, executors) → `@lru_cache` singleton factory
  function, e.g. `get_monitoring()`, `get_llm_unit_of_work_factory()`.
- Use cases → fresh instance per call, concrete adapters injected as kwargs.
- **API**: factories live in `infrastructure/entrypoint/api/factories/`,
  wired via FastAPI `Depends()` **at the router**, not in `fastapi_app.py`.
- **Celery**: factories live in `infrastructure/workflows/celery/factories.py`
  — worker-only, not shared with the API's `entrypoint/api/factories/` (the
  two run as separate poetry projects, see below). Same rules as the API:
  `@lru_cache` singleton functions for stateless adapters, plain functions
  returning a fresh use case per call. `alert_review_workflow.py` (the
  workflow runner) is the only consumer today; it must not construct
  adapters or use cases inline.
  This is also why `monitoring/` and `llm/` factories live directly under
  `infrastructure/`, not under `entrypoint/api/factories/`: both the API and
  the worker need to import them without pulling in FastAPI.

## Two (really three) separate poetry projects — deps must go in the right ones

`deploy/requirements/pyproject.toml` (API) and `pyproject.worker.toml`
(Celery worker) are independent Poetry projects with **separate lock
files**. A dependency used by code that runs inside a Celery task (e.g. the
LLM/monitoring adapters) must be added to **both** files or the worker
container `ImportError`s at task runtime. `poetry lock` needs Python 3.11
(`pyenv shell 3.11.9` locally) and BBVA's `bbvarepo` Artifactory source
configured — neither is available in a bare sandbox, expect to run it
yourself.

`pyproject.mcp.toml` is a **third** independent project (`infrastructure/
entrypoint/mcp/`, the FastMCP model-serving service) — an explicit, agreed
exception to "two projects": it needs the ML inference stack (xgboost/
sklearn/pandas/joblib/shap) that neither the API nor the worker's other code
needs, and runs as neither FastAPI nor Celery. It does share the
feature-building code in `infrastructure/workflows/celery/model_training.py`
with the worker (training and scoring must build features identically), so a
dependency that module needs (pandas/numpy/xgboost/scikit-learn/joblib) goes
in **both** `pyproject.worker.toml` and `pyproject.mcp.toml` — `shap` is the
one exception, needed only by the MCP project (explanations are computed at
serving time, not at training time).

## Testing conventions

- **Hand-written in-memory fakes**, local to the test file. No
  `unittest.mock`, no shared `conftest.py` (none exists in the repo).
  Pattern: `class InMemoryXRepository` / `class RecordingXPort(XPort)` that
  records what it was called with; assert on the fake's recorded state plus
  the returned DTO. See `tests/test_application/test_use_cases/test_start_alert_test_workflow.py`.
- For SDK-backed adapters, prefer the SDK's own in-memory test double over a
  hand-rolled mock when one exists (e.g. OpenTelemetry's
  `InMemorySpanExporter` — see `tests/test_infrastructure/test_monitoring/`).
- Test tree mirrors `src/`: `tests/test_application/test_use_cases/`,
  `tests/test_infrastructure/test_<domain>/`.
- Run: `GENAI_ENVIRONMENT=test pytest` (root `pytest.ini` — ignore the
  `[tool.pytest.ini_options]` block in `deploy/requirements/pyproject.toml`,
  it's a different project and not the one that runs when you `pytest` from
  repo root).

## Directory hygiene — check before creating

This codebase has accumulated duplicate/dead scaffolding before (a
`infrastructure/queue/` singular dir that was a dead re-export shim of
`infrastructure/queues/` plural — deleted). Before adding a new
module/folder:

1. `grep -rn` the concept first — a port, factory, or config var for it may
   already exist (dead or live). `src/infrastructure/core/config.py`
   specifically has several vars copy-pasted from a sibling GenAI project
   that looked live but were unused (`OTEL_ENDPOINT`, `OPENAI_*`,
   `PHOENIX_*` were dead until this session wired `OTEL_ENDPOINT`/
   `OPENAI_*` into real adapters — `PHOENIX_*` is still dead, do not use it,
   the app must stay OTLP-only, see below).
2. Singular vs plural, one canonical spelling per concept — `queues/` not
   `queue/`.
3. One factory function per port per adapter choice — don't add a second
   `get_x()` that does the same thing under a different name.

## Observability — OTLP is the only contract

The app must **never** import or configure Tempo/Loki/Prometheus/Grafana/
MinIO/Phoenix/Langfuse/LangSmith directly. `OTEL_ENDPOINT` (OTLP) is the
only observability variable application code knows about — the Collector is
the sole boundary. Local stack: `deploy/local/docker/observability/`,
`make observability-up` / `observability-down`. Raw prompt/completion
content is opt-in via `OTEL_CAPTURE_LLM_CONTENT` (default `false`) — never
flip that default.

## Alert / workflow domain state (as of this writing)

- `AlertRecord` (`application/ports/alert_port.py`) is the canonical alert
  shape — compose it into new DTOs (`alert: AlertRecord` field), don't
  re-declare its fields. Dataclass inheritance works too but every
  `AlertRecord` subclass field needs a default (its last 3 fields already
  have defaults, Python forbids non-default fields after that in the MRO).
- The 7 `LINEAR_STEPS` (`pre_process`, `profiling`, `classification`,
  `adversarial`, `analyst`, `executor`, `post_process`) are **still
  placeholder logic** inline in
  `infrastructure/workflows/celery/alert_review_workflow.py`, passed a raw
  `context: dict[str, Any]` between steps. Migrating each into a real
  `application/use_cases/alerts/<step>.py` use case (composing
  `LLMUnitOfWorkFactory` + `MonitoringPort`) is planned but **not done** —
  don't assume it exists.
- `application/ports/audit_port.py` (`AuditLogRepository`) is an unrelated,
  older concept — a flat per-tool-call audit log CRUD repo. Don't confuse it
  with `monitoring_port.py` (the span/CoT/dependency tracker built this
  session) or merge them without asking; they solve different problems.
