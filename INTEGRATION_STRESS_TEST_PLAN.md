# Integration & Stress Test Plan

Status: **plan only, nothing implemented yet.** Written 2026-09-03.

## Current state (verified)

- All existing tests (`tests/test_application/`, `tests/test_infrastructure/`) are
  unit tests: hand-written in-memory fakes / `dependency_overrides`, no
  network calls. Confirmed via grep — no `moto`, `localstack`, `testcontainers`,
  or real `boto3`/`redis`/`opensearch-py` client usage anywhere in `tests/`.
- `deploy/local/docker/docker-compose.yml` already defines real backing
  services for local dev: `dynamodb` (dynamodb-local), `redis`, `minio`,
  `opensearch`, plus `api`/`worker` containers. None of these are exercised
  by the test suite today.
- No load/stress tooling exists in the repo (`locust`/`k6`/`artillery`: zero
  hits).
- `pytest.ini` at repo root is the one that runs (`testpaths = tests`); the
  `[tool.pytest.ini_options]` block in `deploy/requirements/pyproject.toml`
  is a separate, unused config per CLAUDE.md.

## Ground rules

- Reuse the existing compose stack. No new test-infra dependency
  (testcontainers, moto) — `docker-compose.yml` + `Dockerfile.test` pattern
  already covers it.
- New tests live under `tests/test_integration/` (real infra) and
  `tests/test_stress/` (load/concurrency), separate from the existing unit
  tree. Marked `@pytest.mark.integration` / `@pytest.mark.stress`, registered
  in `pytest.ini`, **excluded from default `make test`** (unit tests must
  stay fast, no docker dependency).
- New Makefile targets: `test-integration` (brings up
  `dynamodb redis minio opensearch` via compose with `--wait`, runs
  `pytest -m integration`) and `stress-test` (runs `api` + deps, runs k6
  scripts against the running container).
- Integration tests hit real adapters through the *real* factory functions
  (`infrastructure/entrypoint/api/factories/`), not fakes — that's the point:
  catch wiring/serialization bugs unit tests structurally can't.
- Each integration test owns its DynamoDB/OpenSearch/MinIO keys (uuid-prefixed)
  and tears them down in a fixture `finally`, so tests can run against a
  shared long-lived local stack without clobbering each other.

## Part 1 — Integration tests

### 1. DynamoDB repository layer — `tests/test_integration/test_persistence/`

One file per repo in `src/infrastructure/persistence/database/dynamodb/repositories/`
(17 repos: `alert`, `async_operation`, `channel_library`, `configuration`,
`dataset_sample`, `dataset_summary`, `flag_library`, `fraud_playbook`,
`marcacion_catalog`, `modus_operandi_library`, `operations_capacity`,
`resolution_method_catalog`, `similar_case_library`, `tag_catalog`,
`taxonomy_library`, `test_run`, `variable_catalog`, `watchlist`, `workflow`).

Method: real `boto3` DynamoDB client pointed at `DYNAMO_ENDPOINT` (compose's
`dynamodb-local:8000`), via the actual `client.py`/`manager.py` factory —
not a mock.

Cases per repo (adapt to the repo's actual port methods):
- create → get round-trip returns identical dataclass (catches
  `serialization.py` encode/decode drift — this is exactly the class of bug
  unit tests with fakes cannot catch, since fakes skip serialization).
- update → get reflects the change; fields not touched are preserved.
- get on missing key → `None`/not-found per port contract, not an exception
  leak from boto3.
- list/query methods → pagination boundary (0 items, 1 item, exactly one
  page size, spanning two pages if the repo paginates).
- delete → get returns not-found; delete on already-missing key is a no-op,
  not an error.
- Any repo with conditional/optimistic-lock writes (`alert_repository`,
  `workflow_repository`, `async_operation_repository` are the likely
  candidates given the alert/workflow status-transition domain) →
  stale-version update raises the expected conflict, not silently overwrites.
- Enum/nested-dataclass fields (heavy in `configuration_repository` per
  `application/ports/configuration_port.py`'s large type list) → round-trip
  every enum member at least once, not just the default.

### 2. API layer — `tests/test_integration/test_entrypoint/`

One file per router in `src/infrastructure/entrypoint/api/routers/` (17
routers). Method: `TestClient(app)` against the **real** app assembly (no
`dependency_overrides`) — full DI chain: router → factory → use case → real
DynamoDB/OpenSearch/MinIO adapter.

Cases per router:
- Happy path for each endpoint (create/get/list/update/delete as applicable)
  — status code, response schema, and a follow-up read confirming the write
  landed in the real store.
- Validation errors (malformed body, missing required field) → 422, not 500.
- Not-found paths → 404, not 500.
- Idempotency where the port implies it (e.g. re-`POST`ing the same
  operation id).
- `alerts_router` and `test_runs_router` specifically: exercise the
  workflow-triggering endpoints (start review, escalate to analyst, execute
  action) since these are the ones that fan out into Celery + multiple repos
  — highest blast radius if wiring is wrong.

### 3. Workflow end-to-end — `tests/test_integration/test_workflows/`

Target: `AlertReviewWorkflowRunner.run` in
`infrastructure/workflows/celery/alert_review_workflow.py`, all 7
`LINEAR_STEPS` (`pre_process`, `profiling`, `classification`, `adversarial`,
`analyst`, `executor`, `post_process`).

Method: Celery in **eager mode** (`task_always_eager=True`, no real broker
needed for this one — keeps it deterministic) but real DynamoDB for
`AlertRecord`/`ConfigurationRecord`/workflow-state persistence. LLM calls
stay stubbed (a `RecordingLLMUnitOfWorkFactory` fake per existing convention
— an LLM integration test is out of scope here, it's a separate concern from
"does the workflow's dynamo/context plumbing work").

Cases:
- Full linear run across all 7 steps for a single alert → final persisted
  `AlertRecord` status and each step's recorded output in DynamoDB matches
  what the runner returned.
- `_run_adversarial_review` feedback loop: force the adversarial step to
  reject `_effective_max_feedback_iterations` times → confirm
  `AdversarialFeedbackLimitExceededError` fires and the persisted state
  reflects exhaustion, not an infinite loop.
- `_escalate_to_analyst` path taken mid-workflow → confirm early-exit skips
  remaining steps and persists the escalation reason.
- Segment resolution (`_resolve_segment`/`_active_segment`) with a
  multi-segment config (per `250f370` multi-segment config work) → correct
  segment picked for a given alert's fields, not just the default/first.
- Context snapshot (`_context_steps_snapshot`) persisted matches what each
  step actually produced — this is the field most likely to silently drift
  since it's assembled by hand across 7 step functions.

### 4. Queue / dispatch round-trip — `tests/test_integration/test_queues/`

Target: dispatchers in `infrastructure/queues/celery/` (`dispatcher.py`,
`alert_action_dispatcher.py`, `dataset_analysis_dispatcher.py`,
`analyst_capacity_import_dispatcher.py`, `analyst_escalation_dispatcher.py`,
`analyst_decision_documenter_dispatcher.py`) + `inspector.py`.

Method: real Celery worker process against compose's `redis` broker (not
eager mode here — the point is to test the actual broker round-trip).

Cases:
- Dispatch → task lands in redis → worker picks it up → `inspector.py`
  reports the correct terminal state (`AsyncExecutionState`).
- Dispatch with a worker that raises → inspector reports `FAILED` with the
  error surfaced, not swallowed.
- `analyst_capacity_import_status_reader.py` reads back a status consistent
  with what the dispatcher wrote, under a real broker round-trip (not
  in-process fakes).

### 5. Vector store (OpenSearch) — `tests/test_integration/test_vector_store/`

Target: `persistence/vector_store/opensearch/` (`index.py`, `search.py`,
`repository.py`, `relations.py`), consumed by the `fraud_knowledge` use
cases (`ingest`, `list_search_related`, `update`, `delete_cascade`).

Method: real OpenSearch container from compose.

Cases:
- Ingest a document → search returns it, with expected ranking for an exact
  vs. fuzzy query term.
- `delete_cascade` removes the document and all its declared relations
  (`relations.py`) — check relation index is actually empty after, not just
  the primary doc.
- Index creation is idempotent (`index.py` re-run against an
  already-existing index doesn't error or wipe data).
- Update changes searchable content (old term no longer matches, new term
  does) — catches stale-index-not-refreshed bugs.

### 6. Object storage (MinIO) — `tests/test_integration/test_object_storage/`

Target: `persistence/object_storage/minio/minio_object_storage_adapter.py`
+ `persistence/dataset/minio/csv_dataset_repository.py`, consumed by
`upload_dataset`/`delete_dataset`/`analyze_dataset` use cases.

Method: real MinIO container from compose.

Cases:
- Upload CSV → download/read back byte-identical.
- Large-ish CSV (a few MB, bigger than any single-part upload heuristic if
  one exists) uploads and reads back intact.
- Delete removes the object; a second delete is a no-op, not an error.
- Upload with a duplicate key → adapter's actual overwrite-or-reject
  contract (check `minio_object_storage_adapter.py` for which it claims,
  test that one).

## Part 2 — Stress tests

Not pytest — perf tooling is a different shape of tool than correctness
tests. Two tracks:

### A. HTTP load — k6 (`tests/test_stress/k6/*.js`)

Why k6: single static binary, no new Python dependency (ladder: don't add a
Python load-test lib when a standalone tool does it better), scriptable
thresholds for pass/fail in CI.

Targets (picked for being the endpoints with real fan-out — DB write +
possible queue dispatch — not the read-only catalog endpoints):
- `POST /alerts/{id}/action` (`execute_alert_action`) — ramp 1→50 VUs over
  2 min, hold 3 min. Threshold: p95 < target latency (fill in once a
  baseline run establishes current numbers — don't invent a number now),
  error rate < 1%.
- `GET /async-operations/{id}/poll` — this is a polling endpoint, so the
  realistic load shape is many clients polling frequently, not ramping
  users. Script: N constant VUs polling every 2s (matching the
  `retry_after_seconds` contract seen in the existing router test) for 5
  min. Threshold: p99 latency, no 5xx.
- `POST /alerts/{id}/escalate` — burst test: 200 requests in a 10s window
  (simulates a bulk-escalation event) rather than a steady ramp.

Each script asserts on k6 `thresholds` (http_req_failed rate, http_req_duration
percentiles) so `make stress-test` can fail CI on regression, not just print
numbers for a human to eyeball.

### B. Concurrency / race correctness — `tests/test_stress/test_concurrent_writes.py`

This part *is* pytest (real correctness assertions, not throughput) —
separate from k6 because it's asserting on data integrity, not latency.

Method: real DynamoDB, `asyncio.gather`/`ThreadPoolExecutor` firing N
concurrent writers at the same record.

Cases:
- N concurrent `execute_alert_action` calls against the *same* alert id →
  final state is one consistent, valid transition (not a torn write); losers
  get the expected conflict error, not a silent overwrite. This is the
  highest-value stress case given `AlertRecord` status transitions are
  central to the whole domain and conditional-write behavior is currently
  untested at any level (see Part 1.1).
- N concurrent workflow-step writes to the same `context_steps_snapshot` →
  no lost updates (each step's contribution present in the final snapshot).
- Burst-dispatch 500 Celery tasks in one batch (queue backpressure, ties
  into Part 1.4's inspector) → all 500 eventually reach a terminal state
  inspectable via `reconcile_async_operations`, none stuck in
  `RUNNING`/`PENDING` past a generous timeout.

## Phasing (suggested, not committed)

1. Repo layer integration (1.1) — smallest slice, unblocks everything else
   since API/workflow tests depend on repos actually working against real
   DynamoDB.
2. API layer integration (1.2).
3. Workflow end-to-end (1.3) — depends on 1 & 2 being solid, otherwise
   failures are ambiguous (repo bug vs. workflow bug).
4. Queue/vector-store/object-storage integration (1.4–1.6) — independent of
   each other, can be done in any order or parallelized across people.
5. Stress (Part 2) — last, since it needs a stable integration baseline to
   distinguish "this is slow" from "this is broken."

## Open questions to resolve before implementation starts

- Baseline latency targets for k6 thresholds — need one real run against
  current code to set numbers, can't guess them.
- Whether CI (Jenkinsfile) should run `test-integration` on every PR (slower,
  needs docker-in-docker or a compose-capable runner) or only on a schedule/
  merge-to-main.
- LLM stub strategy for workflow integration tests — reuse
  `RecordingLLMUnitOfWorkFactory`-style fake from
  `test_start_alert_test_workflow.py`, or something new; needs a look at
  what that fake currently supports before deciding.
