# aria-api

API for the novel massive fraud agent for BBVA company.

## Tests

The testing guide, including the Vector Store unit, API, and Docker integration
commands, is available in [tests/README.md](tests/README.md).

## Local authentication

`POST /api/v0/auth/login` returns an HS256 JWT; clients send it as a Bearer
token and obtain the assigned role and fixed permissions from
`GET /api/v0/auth/me`. To provision a local user, set `AUTH_BOOTSTRAP_TOKEN`
and submit `POST /api/v0/auth/users` with that value in `X-Bootstrap-Token`.
Set a unique `AUTH_JWT_SECRET` in every non-local environment.

Use `make create-local-user` to provision a user interactively. It asks for
all identity fields, the password, and the bootstrap token at runtime; neither
password nor token is written to disk or echoed to the terminal.

Before provisioning, run \`make local-auth-up\`; it prompts for the JWT signing
secret and bootstrap token, starts the local API with them, and does not persist
either value. Then run \`make create-local-user\` and enter the same bootstrap
token. The API must be rebuilt after pulling authentication changes.

## Local Docker Stack

Build and run the local API, DynamoDB, Redis, and Celery worker:

```bash
make local-docker-build
make local-docker-run
```

Stop the stack:

```bash
make local-docker-stop
```

Default local endpoints:

| Service | URL |
|---|---|
| API health | http://localhost:8000/health |
| API docs | http://localhost:8000/docs |
| DynamoDB local | http://localhost:8002 |
| Redis | localhost:6379 |

## Async Operations

Long-running transactional requests are tracked in the `async_operations`
table before being dispatched to the selected async executor.

Current local executor:

```text
ASYNC_EXECUTOR_BACKEND=celery
```

The API flow is:

1. Create `async_operations` row as `PENDING`.
2. Dispatch through the selected `AsyncExecutor`.
3. Store executor metadata such as backend and Celery task id.
4. Mark the operation as `DISPATCHED`.
5. Worker updates status to `RUNNING`, then `SUCCEEDED` or `FAILED`.

## Alert Workflow

Start the current test workflow:

```bash
curl -X POST http://localhost:8000/api/v0/alerts/test \
  -H "Content-Type: application/json" \
  -d '{
    "created_by": "local",
    "event": {
      "eventId": "event-1",
      "eventType": "paymentRT",
      "customerId": "10264559",
      "amount": {"baseValue": 680871.0}
    }
  }'
```

The endpoint creates:

- an `alerts` record
- an `async_operations` record
- a `workflow_executions` record
- `workflow_step_executions` records as the worker runs each step

Current placeholder workflow:

```text
pre_process
profiling
classification
adversarial
classification  # one feedback loop when adversarial requests it
analyst
executor
post_process
```

The workflow backend is Celery today, isolated under
`src/infrastructure/workflows/celery`.

## Reconciliation

If API state and backend execution state diverge, run reconciliation:

```bash
curl -X POST http://localhost:8000/api/v0/async-operations/reconcile \
  -H "Content-Type: application/json" \
  -d '{"limit": 100}'
```

The reconciler checks active operations in `async_operations`, asks the
selected backend inspector for execution state, and updates DB status when the
backend can prove `RUNNING`, `SUCCEEDED`, or `FAILED`. Unknown backend state is
reported as `UNKNOWN` and left unchanged.

In Docker Compose, the separate `scheduler` service runs Celery Beat and
enqueues this reconciliation every 60 seconds by default. Keep exactly one
scheduler replica per environment. Configure the interval and batch size with
`CELERY_RECONCILE_INTERVAL_SECONDS` (minimum 10) and `CELERY_RECONCILE_LIMIT`
(1–1000).

## LLM Unit of Work & Monitoring

Two application-layer abstractions back every step that talks to an LLM:

- `LLMUnitOfWorkFactory` / `LLMUnitOfWork`
  (`src/application/ports/llm_unit_of_work_port.py`) — instantiated once per
  logical LLM call (e.g. "write_email" vs "review_email"), takes a
  `MonitoringPort` instance, and is the only thing a step use case uses to
  talk to an LLM. Concrete adapter: LangChain + Azure AI Foundry
  (`src/infrastructure/llm/langchain`), model passed in per call by the
  caller.
- `MonitoringPort` / `MonitoringSpan`
  (`src/application/ports/monitoring_port.py`) — technology-agnostic audit
  abstraction. Tracks start time, execution time, dependencies, and exposes
  `write_input` / `write_result` / `write_inner_logs` (CoT) /
  `write_operation_metas`. Concrete adapter: OpenTelemetry
  (`src/infrastructure/monitoring/opentelemetry`), exporting spans over OTLP
  to `OTEL_ENDPOINT`.

Application code never depends on the observability backend directly —
OpenTelemetry/OTLP is the only contract it knows. Raw prompts/completions are
opt-in: set `OTEL_CAPTURE_LLM_CONTENT=true` to attach them to spans;
otherwise only size/shape metadata is recorded.

## Local Observability Stack

An OTel Collector + Tempo + Loki + Prometheus + Grafana + MinIO stack for
local tracing/metrics/logs, all fed through a single OTLP endpoint:

```bash
make observability-up
```

Stop it:

```bash
make observability-down
```

| Service | URL |
|---|---|
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| MinIO console | http://localhost:9001 |
| OTLP gRPC | http://localhost:4317 |
| OTLP HTTP | http://localhost:4318 |

Grafana comes with Tempo/Loki/Prometheus datasources and two dashboards
(Service Overview, LLM Overview) pre-provisioned — no manual UI setup. Tempo
and Loki store data in MinIO (S3-compatible), the same contract used for S3
in AWS.

The application must only ever be configured with `OTEL_ENDPOINT` — never
with Tempo/Loki/Prometheus/Grafana/MinIO endpoints directly. The Collector is
the sole boundary between the app and these backends, so any of them can be
swapped later without touching application code.

## Verification

Run unit tests:

```bash
GENAI_ENVIRONMENT=test pytest
```
