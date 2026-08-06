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
