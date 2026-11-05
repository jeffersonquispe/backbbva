# aria-api — architecture guide for Claude

API for the massive fraud agent for BBVA. Hexagonal / clean architecture.
Read this before adding files — most "new" needs already have a home and a
pattern to copy.

## Frontend API access

Browser and frontend E2E requests must use the same-origin `/api/...` path,
which nginx proxies to this service. Do not have those clients call
`localhost` with an API port or `127.*`; use the configured frontend/API
location and its `/api/...` proxy path.

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
   Examples: `alert_port.py`, `workflow_port.py`.
2. **Single-behavior abstraction** → `ABC` with `raise NotImplementedError`
   (or `@abstractmethod`), one primary method, swappable backend.
   Examples: `workflow_executor_port.py` (`WorkflowExecutor.start`),
   `async_execution_inspector_port.py` (`AsyncExecutionInspector.inspect`),
   `monitoring_port.py` (`MonitoringPort.start`),
   `llm_unit_of_work_factory_port.py` (`LLMUnitOfWorkFactory.create`).

Keep boundary-only request/result records beside their port contract. Stable
business entities and state enums live under `src/domain/<context>/`; port
modules may import and re-export those types for compatibility, while
application use cases should import them directly from the domain. Do not add
a separate application-level `models` module.

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
  (adapters + workflow use cases) and `task_factories.py` (task-level wiring:
  datasets, escalation/documenter, research collaborators)
  — worker-only, not shared with the API's `entrypoint/api/factories/` (the
  two run as separate poetry projects, see below). Same rules as the API:
  `@lru_cache` singleton functions for stateless adapters, plain functions
  returning a fresh use case per call. The `review_*_steps.py` step
  executors and `entrypoint/worker/celery/tasks.py` consume them; neither
  may construct adapters or use cases inline (enforced by
  `tests/test_architecture/`, run `make test-architecture`).
  This is also why `monitoring/` and `llm/` factories live directly under
  `infrastructure/`, not under `entrypoint/api/factories/`: both the API and
  the worker need to import them without pulling in FastAPI.

## Separate Poetry projects — deps must go in the right ones

`deploy/requirements/pyproject.toml` (API), `pyproject.worker.toml` (main
Celery worker), `pyproject.training-worker.toml` (training worker),
`pyproject.mcp.toml` (model serving), and `pyproject.simulator.toml` (event
simulator) are independent Poetry projects with separate dependencies. The
main worker delegates scoring to MCP and training to the training worker;
keep XGBoost, scikit-learn, NumPy, and joblib out of its runtime. Pandas
remains for the optional history research task. Training dependencies belong
in both the training worker and MCP projects, which share feature-building
code. `poetry lock` needs Python 3.11 (`pyenv shell 3.11.9` locally) and
BBVA's `bbvarepo` Artifactory source configured.

`pyproject.mcp.toml` is the FastMCP model-serving service project. It owns
the ML inference stack and loads model bundles. The training worker owns
training and evaluation. The main alert worker calls MCP over HTTP and does
not load the model runtime. XGBoost's native TreeSHAP (`pred_contribs=True`)
provides explanations — don't add the heavy `shap` package.

Each service has Dockerfiles in `deploy/local/docker/`: `Dockerfile.<svc>`
(local, public PyPI/Docker Hub) and `Dockerfile.<svc>.okd` (OKD: base image
and Python libs pulled through BBVA Artifactory, needs `ARTIFACTORY_USER`/
`ARTIFACTORY_PASSWORD` build args). Both are multi-stage (Poetry and
credentials stay in the `builder` stage) — a change to one (system packages
like `libgomp1`, CMD, ports) must be mirrored in the other.

## Testing conventions

### Required Playwright E2E for every change

- Every new feature or behavior change must update its relevant Playwright E2E
  coverage and run that scenario against the current local stack through nginx
  at `http://localhost` (port 80). The app is served at `/`; browser API
  requests must use the same-origin `/api/...` proxy path. E2E scenarios load
  real data through the API and must not mock or fulfill API requests.
  Check `make local-env-status` first; reuse a running stack only when its
  recorded workspace fingerprint matches, otherwise rebuild it.
- Unit tests and standalone API smoke checks do not replace the real E2E. A
  change is not complete until the relevant E2E passes.
- If credentials, Docker, external services, or missing fixture data block the
  run, report the exact blocker and leave the change explicitly incomplete; do
  not mark E2E as passed based on a different scenario.
- Backend observability E2E: `make e2e-observability`. It covers the real
  dashboard and monitor pages, their metrics API reads, HTTP audit recording,
  and expired metrics-rollup cleanup against the local DynamoDB-compatible
  service. Extend this scenario when those contracts change.
- Full real API browser suite: `make e2e-all-local`.

### Local environment reuse and E2E history

- Before starting or rebuilding the local stack, run `make local-env-status` and
  `make e2e-history`. The status command shows Compose services and compares the
  current backend/frontend workspace with the most recent recorded launch. If
  required services are already running and the fingerprint matches, reuse
  that stack; do not call `make local-docker-run` just to check it, because
  that target restarts services. If the services are stopped or the fingerprint
  changed, start the stack with `make local-docker-run`.
- `make local-docker-run` records a launch snapshot in
  `/tmp/aria-e2e-history.jsonl`. Playwright runs launched by the local E2E
  runners also record their result, duration, suite/specs, command, and full
  output under `/tmp/aria-e2e-runs/`. `make e2e-history` lists recent events.
- A workspace snapshot includes backend and frontend branch, HEAD commit and
  commit time, porcelain `git status`, changed paths, and for each changed
  regular file its SHA-256, size, and modification time. Passing E2E results
  are reusable for 24 hours only when suite, code fingerprints, and recorded
  run settings match. `E2E_FORCE_RUN=1` forces a rerun. Treat a changed
  fingerprint as evidence that the recorded run does not cover the current
  files; use the listed paths/commit data to decide what needs rebuilding and
  retesting.

### Intensive local agent E2E worker scaling

Before intensive agent-pipeline E2E runs, inspect available host/container
CPU and memory, current worker usage, and the worker service's configured
concurrency. Choose a safe worker replica count from those measurements,
leaving at least 20% memory headroom; then start/scale the test workers from
the CLI via `LOCAL_DOCKER_TEST_WORKERS=<count> make local-docker-run` (or the
corresponding Compose `--scale` command). Do not recreate or scale workers
while a test is actively processing jobs. The local baseline measured on
2026-10-22 was 15 CPUs and 7.75 GiB RAM; three total test-worker replicas
were the conservative setting for H9/H11. Re-measure on each machine/run
rather than assuming that count is universally safe.

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
- For API route or method changes, run `make test-api-contracts`. It compares
  all frontend API-client route/method shapes with the generated backend
  OpenAPI surface. It does not compare every request/response field: add or
  update focused API response/request contract tests for changed schemas,
  preserving the active/versioned dynamic alert schema contract.
- For Celery task changes, run
  `GENAI_ENVIRONMENT=test pytest tests/test_infrastructure/test_entrypoint/test_celery_task_signature_contracts.py`
  and the task's focused behavior tests. All registered project tasks must
  retain annotated input/output signatures and JSON message serialization.
- For domain or workflow invariants, add Hypothesis properties beside the
  corresponding unit tests where generated inputs add value. Existing property
  coverage includes rule comparisons, history selection, mature sampling and
  partitioning, alert rollups, and async-operation reconciliation.
- To assess endpoint removal, use
  `python scripts/report_api_endpoint_usage.py --from-day YYYY-MM-DD
  --to-day YYYY-MM-DD --include-unused` against the intended environment. The
  report combines frontend references and HTTP audit traffic. A route with no
  frontend reference or no traffic in the selected window is only a candidate
  for review; check external consumers and periodic callers before removal.

## Before you call a change done — always run these

1. `make lint` — ruff + mypy against `.lint-baseline.json`; fails only if the
   error count **grows**. If you fixed errors, run `make lint-baseline` to
   lower the baseline and commit it. Never commit a baseline that went *up*:
   fix the new errors instead (`lint-baseline` rewrites whatever the current
   count is, so check the diff of `.lint-baseline.json` first).
2. `make test-architecture` — AST fitness tests in `tests/test_architecture/`
   (import boundaries, worker wiring, service dependencies, composition smoke,
   and `test_conventions.py`: port shapes, `@lru_cache` on adapter factories,
   orphan `Config` fields, fake naming + test-tree mirror, Dockerfile
   local/OKD parity, shared worker/MCP deps). Ratcheted: a new violation
   fails, a resolved one must be deleted from its `KNOWN_VIOLATIONS`.
   **Baseline policy: a new violation is fixed, never added to
   `KNOWN_VIOLATIONS`** — the set only shrinks (the same applies to
   `.lint-baseline.json`).
3. `GENAI_ENVIRONMENT=test pytest` for the code you touched.

Jenkins runs 1 and 2 as the `Lint` and `Architecture` stages (see
`Jenkinsfile`); a red stage blocks the build.

`pre-commit install` (config: `.pre-commit-config.yaml`) runs `make
test-architecture` and ruff on every commit, so 1–2 fail locally before CI.
Tests under `tests/test_application/` and `tests/test_domain/` must not import
`src.infrastructure` (use an in-memory fake; a test that needs the real
adapter goes in `tests/test_infrastructure/`).

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

Span dimension attributes use the `ATTR_*` constants /
`span_dimension_attributes(snapshot)` in `application/ports/monitoring_port.py`
(names mirror `AlertMetricsSnapshot`). **Never put `customer_id` or the exact
amount on a span or metric attribute** (a test in
`test_alert_review_workflow.py` enforces it); metric attributes stay
low-cardinality. Runbook: `docs/OBSERVABILITY_RUNBOOK.md`.

Audit logging uses the `AuditPort` contract in
`application/ports/audit_port.py`; HTTP requests and persisted object mutations
are recorded through the infrastructure audit adapters. Keep audit transport
and storage details out of application use cases.

## Business metrics — snapshot + rollups (DynamoDB, not telemetry)

Design: `docs/OBSERVABILITY_STRATEGY.md`; outstanding deployment, security,
performance, and business decisions are tracked in `PENDIENTES.md` §6.

- Each alert carries `AlertRecord.metrics: AlertMetricsSnapshot | None`
  (`alert_port.py`). Two labels only: `mark` (`fraud`/`no_fraud`/`pending`,
  the decision by ARIA/analyst/voicebot, immutable once non-pending) and
  `fraud_label` (reality; starts = `mark`, corrected by the fraud team).
  FP / undetected fraud = `mark` ≠ `fraud_label`, `pending` excluded. Don't
  add a third "ground truth" field.
- **Only `RecordAlertMetricsEvent`
  (`application/use_cases/metrics/record_alert_metrics_event.py`) writes the
  snapshot and the `alert` rollups** — one `TransactWriteItems` guarded by
  `snapshot_version`, so Celery retries never double count.
  `AlertRepository.update` deliberately can't touch the snapshot. New hook
  points call it with an `AlertMetricsEventType`; don't write rollups
  elsewhere. Two sanctioned exceptions, rows only: `RecordWorkflowStepMetrics`
  / `EvaluateAlertReasoning` (technical + judge data types, idempotent via
  `apply_once` markers) and `ReconcileAlertRollups` (nightly R7, conditional
  `correct()` on the row `rev`).
- `metrics_rollups` table: levels day (TTL 90 d) / month / year, 24
  hour-of-day slots stored as flat attributes `<measure>__h<HH>` (DynamoDB
  can't `ADD` into nested paths). Only additive measures. Bucketed by the
  alert's Bogotá date; late changes apply −old/+new to every live level.
- Reads go through `range_planner.plan(...)`; the API returns
  numerators/denominators and the frontend computes rates.
- Alerts GSIs: `CreatedDayIdx` (history, backfill, reconciliation) and
  `StatusIdx` (queue, live funnel) — never `Scan` the alerts table.

## Alert / workflow domain state (as of this writing)

- `AlertRecord` (`application/ports/alert_port.py`) is the canonical alert
  shape — compose it into new DTOs (`alert: AlertRecord` field), don't
  re-declare its fields. Dataclass inheritance works too but every
  `AlertRecord` subclass field needs a default (its last 3 fields already
  have defaults, Python forbids non-default fields after that in the MRO).
- Workflow orchestration lives in
  `application/use_cases/alerts/run_alert_review_workflow.py`
  (`RunAlertReviewWorkflowUseCase`: step order, status transitions,
  adversarial feedback limits, escalation, terminal outcomes; pure helpers
  in `alert_review_policy.py`, incl. `LINEAR_STEPS`). Each step's body is
  an `AlertReviewStepExecutor` port; the worker adapter is
  `infrastructure/workflows/celery/review_step_executor.py` over
  `review_{intake,agent,action}_steps.py`, built by
  `task_factories.get_run_alert_review_workflow_use_case()`. Steps are still
  functions passed a raw `context: dict[str, Any]` — typed run state and
  per-step `application/use_cases/alerts/<step>.py` use cases are **not
  done**; don't assume they exist.
- Fraud-knowledge use cases are internal capabilities used by worker/API
  flows. They intentionally have no dedicated public router or API surface;
  do not register one without an architecture decision.

## Vector Store generations — building never publishes

Design: `docs/VECTOR_STORE_GENERATIONS.md` (#30). An instance has an editable
manifest and immutable OpenSearch generations
(`vector_store_generations`: building/ready/failed/retired).
`BuildVectorStoreGenerationUseCase` loads a new generation (or reuses the READY
one with the same fingerprint) and never touches older ones. Every saved
configuration pins `vector_store_instance_id` + `vector_store_generation`
(`PinConfigurationVectorStoresUseCase`); tests and production search exactly
that pin. Changing which generation production searches **only** goes through
an approved configuration deploy request — direct activation with different
pins is a 409. Don't add another publish path, don't search "latest" from the
workflow, and don't delete generation documents outside
`CleanupVectorStoreGenerationsUseCase` (nightly, protects active/rollback/
pending/open work). Optimizer and H12 vector-store pins use the generation
number as their version.

## Assistant chat is asynchronous — the API never calls the LLM

`POST /agent/sessions/{id}/messages` only runs `ChatWithAgentUseCase.accept`
(validate, mask, store the user turn) and queues `agent.chat_reply` through
`AgentChatDispatcher`; it answers `202` with `assistant_message: null`. The
worker (`aria-agent-chat-worker`, queue `CELERY_AGENT_CHAT_QUEUE`, separate from
the optimizer's `agent` queue so a long candidate never delays an answer) runs
`answer` (retrieval, tool loop, LLM) and stores the reply under
`<client_message_id>:assistant`. Clients poll `GET .../messages?after_seq=`.
Everything is idempotent by `client_message_id`; after the last retry the worker
stores a closing message with a safe `error_code` (never provider text), and a
retry from the UI is a new message id. Do not call the LLM from an API route:
queue it, as chat does. The API composes the use case with a responder that
raises; the worker composes the real one in `workflows/celery/factories.py`.

## Cold fraud-history archive — index, lookup and legal hold

`fraud_history.retention` writes one object per creation day, each alert its
own gzip member, and indexes `alert_id` → object + byte range
(`fraud_history_archive_index`) before deleting hot rows.
`GET /fraud-history/archive/{alert_id}` (permission `fraud_archive`) reads one
alert with a range request and refuses content that fails its SHA-256. Objects
from before the index are indexed with `make fraud-history-archive-index-backfill`.
Legal holds (`legal_holds` table, permission `legal_hold`, manager only) keep
live alerts out of the archive and protect the day object of archived ones from
retention sweeps. These use cases write their own `AuditPort` entries because
the HTTP audit only records the route template, not the `alert_id`.

## Project graph — graph-RAG context for the chat agent

`src/infrastructure/agents/project_graph/project_graph.json` is a generated
property graph of ARIA: views, components, user actions, frontend API calls,
endpoints, use cases, ports/adapters, API resources, assets, roles/permissions,
plus curated **tasks** (ordered how-to steps) and **concepts** (domain terms).
Never edit the JSON by hand: `make project-graph` rebuilds it from
`scripts/ts_scan.mjs` (frontend, TypeScript compiler API), Python `ast` over the
routers/use cases/ports/adapters, and `scripts/project_graph_curated.json`
(descriptions, tasks, concepts; every id it references is validated, a dangling
one fails the build). `make project-graph` generates descriptions for new,
uncurated components through the configured LLM and caches them in
`scripts/project_graph_descriptions.json`; ordinary builds reuse this cache,
and `make project-graph-check` verifies the result deterministically. Rebuild
whenever routes, components, API functions, routers, roles or curated graph
data change. Jenkins checks out the matching frontend branch before checking
staleness.

Retrieval (`RetrieveProjectContextUseCase`): BM25 over name/keywords/
description with a light Spanish stemmer + intent boosts ("qué es" → concepts,
"cómo/dónde" → tasks) + history terms, optionally fused (RRF) with embeddings
(`ProjectGraphSemanticSearch`, only when `EMBEDDING_MODEL` is set), the current
view as a seed, then hub-damped 2-hop spreading activation over typed edges.
**Role filtering is server-side**: `ProjectGraph.hidden_for(role)` drops views,
tasks, actions, components, API calls and endpoints the role cannot reach
(`ROLE_NAV` + `ROLE_PERMISSIONS` + `require_permission`); the role comes from
the authenticated user, never from the message or the model. `page_path` is only
a lookup key. `ChatWithAgentUseCase` injects the result as `project_context`,
gives the model two read-only tools (`search_project`, `describe_node`, scoped
to the same role/page and capped at 2 rounds) and stores validated
`references` (chips; only nodes the model was shown and the role can reach) and
`context_used` on the assistant message.

Quality gate: `tests/test_infrastructure/test_agents/project_graph_golden.json`
is the golden question set (every question must retrieve an expected node, for
every role nothing hidden may leak). Add a golden question whenever a real
question is answered badly, then fix the graph or the retrieval.

The optimizer orchestrator also reads the graph's four `optimizer-lever-*`
concepts to route hypotheses to configuration, library, model or vector-store
specialists. It passes those descriptions to the selected specialist as
bounded project context; the graph augments routing and never grants authority
to edit or activate a candidate.
