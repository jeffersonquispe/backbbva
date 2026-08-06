# aria-api

API for the novel massive fraud agent for BBVA company.

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

## Verification

Run unit tests:

```bash
GENAI_ENVIRONMENT=test pytest
```
