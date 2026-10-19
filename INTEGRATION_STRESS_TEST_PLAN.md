# Integration & Stress Test Plan

Status: **backlog; partial integration and load-test coverage already exists.**
Initial inventory written 2026-09-03; task breakdown updated 2026-10-18.

## Current state (verified)

- Most tests under `tests/test_application/` and
  `tests/test_infrastructure/` are isolated tests using in-memory fakes or
  `dependency_overrides`.
- `deploy/local/docker/docker-compose.yml` already defines real backing
  services for local dev: `dynamodb` (dynamodb-local), `redis`, `minio`,
  `opensearch`, plus `api`/`worker` containers. Some are exercised by
  `docker_integration` tests for metrics, reservations, vector store, MinIO
  retention, and event simulation; see focused Makefile targets.
- Load tooling exists: Locust targets and synthetic metrics load/query
  benchmarks. The endpoint scenarios and concurrent-write correctness cases
  proposed below remain gaps.
- `pytest.ini` at repo root is the one that runs (`testpaths = tests`); the
  `[tool.pytest.ini_options]` block in `deploy/requirements/pyproject.toml`
  is a separate, unused config per CLAUDE.md.

## Ground rules

- Reuse the existing compose stack. No new test-infra dependency
  (testcontainers, moto) — `docker-compose.yml` + `Dockerfile.test` pattern
  already covers it.
- Keep real-infrastructure tests under `tests/test_integration/`; existing
  suites use the registered `docker_integration` marker and focused Makefile
  targets. Inspect `tests/stress/` and existing Locust/synthetic-load targets
  before adding tools or targets.
- Integration and stress suites stay out of default `make test`; unit tests
  must remain fast and Docker independent. Prefer focused targets and only add
  an aggregate target if task 0.3 finds it useful.
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

## Task backlog

This section turns the coverage proposal above into reviewable work. A task is
done when its artifact exists, its focused command passes against the stated
service, and it can be rerun without damaging shared local data. Keep tasks as
separate PR-sized changes where practical. Existing coverage should be recorded
in a matrix, not recreated under a new name.

### 0. Inventory and test-runner foundation

**0.1 Reconcile the plan with the repository.** Review `tests/test_integration/`,
`tests/stress/`, `pytest.ini`, `tests/README.md`, and related Makefile targets.
Create a coverage matrix for repositories, routers, services, existing tests,
commands, and uncovered behavior. Done when every area below is classified as
covered, partial, or missing, with runnable commands for existing coverage.

**0.2 Document integration conventions.** Use the registered
`docker_integration` marker unless a concrete need for another marker emerges.
Document service prerequisites, ports, setup/teardown, shared versus disposable
stack, and environment variables. Confirm default `make test` remains Docker
independent. Done when a developer can run a focused group from a clean
checkout without guessing setup.

**0.3 Decide on an aggregate target.** Decide whether to keep focused targets
only or add an aggregate target that invokes them. Preserve focused targets;
an aggregate must avoid starting unrelated services and be documented in
`tests/README.md`.

### 1. DynamoDB repository integration

**1.1 Build the repository matrix.** Enumerate actual repository modules and
port methods, reconcile the count in Part 1.1 with the current tree, identify
coverage already provided by metrics/reservation/vector-store/simulation
tests, and record each uncovered repo's schema, methods, conditional writes,
and safe key strategy. Done when every repo has a row and no test assumes
unsupported CRUD operations.

**1.2 Add isolated table/key setup.** Reuse the local DynamoDB client/schema
conventions. Create only needed tables/indexes, use UUID-prefixed keys, and
clean up in fixture teardown. Never clear shared tables. Done when tests pass
twice and alongside another run without collisions or deleting other data.

**1.3 Add real serialization round-trips.** For each uncovered repository,
write then read through the real adapter and DynamoDB Local. Include nested
dataclasses, enums, optional values, datetime/decimal types where applicable;
assert decoded values. Done when serialization drift fails a focused test.

**1.4 Add applicable contract edges.** Cover missing-key behavior, update
preservation, deletion, query/list boundaries and pagination only where the
port supports them. Exercise page boundaries with a controllable small page
size. Test stale-version conflicts only for adapters that implement them. Done
when each applicable port behavior has a real-adapter case.

### 2. API assembly and router integration

**2.1 Map routers and dependencies.** Inventory actual routers, endpoints,
factories, adapters, and external dispatch. Define setup/cleanup and identify
which routes need a broker or workflow. Done when the router count and test
strategy match the current app.

**2.2 Establish a real-app fixture.** Use normal app assembly and real adapter
factories without `dependency_overrides` for the behavior under test. Point
services at local dependencies and use unique records. Start with one read/write
route proving route → factory → use case → persistence and cleanup.

**2.3 Add endpoint cases router by router.** For each applicable endpoint,
cover happy path and follow-up real-store read, validation response, and
not-found response. Add idempotency only if promised by its contract. Done
when each router has a focused command and cases for its applicable behavior.

**2.4 Separate enqueue from execution.** For alert review, escalation, and
action endpoints, define whether HTTP guarantees durable enqueue or completed
work. Test enqueue with the real broker (task 4) and execution in the workflow
harness (task 3); do not claim task acceptance proves workflow completion.

### 3. Alert review workflow persistence

**3.1 Verify current workflow contract.** Read current runner, executors,
transitions, config lookup, and tests before assuming the plan's seven-step
shape. Confirm current step list, persisted records, and useful assertions. Done
when proposed cases match current code and test contracts rather than private
helper details.

**3.2 Build deterministic collaborators.** Reuse/extend a recording LLM fake
only for LLM calls; keep alert/config/workflow repositories real. Use eager
Celery only if the execution path actually requires it. Done when external LLM
nondeterminism is removed while persistence/wiring remains real.

**3.3 Test success and context persistence.** Run one alert through all current
steps; assert terminal status, outputs, context snapshot, and workflow state
after a fresh repository read. Done when persisted state agrees with runner
output.

**3.4 Test feedback limit and escalation.** Force rejection through the
configured bound and assert terminal/error state plus persisted count. Trigger
mid-run escalation and assert later steps stop and the reason persists. Done
when both paths are deterministic and bounded.

**3.5 Test segment selection.** Use a multi-segment configuration and an alert
that matches a non-default segment; assert the selected segment affects
persisted context. Done when selecting the first/default segment unconditionally
would fail the test.

### 4. Celery and Redis integration

**4.1 Map dispatcher contracts.** Inventory dispatchers, tasks, operation
records, queues, result inspection, and retry semantics. Start with one
representative task. Done when every dispatcher maps to its expected terminal
state source.

**4.2 Create disposable broker/worker harness.** Start Redis and a real Celery
worker using the local compose network or isolated compose project. Use unique
task IDs/queues; teardown only resources created by the test target. Done when
a task crosses process boundaries and can be inspected without eager mode.

**4.3 Test success and failure round-trips.** Dispatch and poll with a bounded
deadline for successful terminal state; dispatch a raising task and assert
failure plus surfaced error. Add dispatcher-specific cases where payload/result
contracts differ. Done when success and failure both cross broker and worker.

**4.4 Verify status reader.** Exercise analyst-capacity import dispatch and
status read through real persistence and broker path. Done when reader output
matches the worker terminal result.

### 5. OpenSearch and MinIO gaps

**5.1 Audit OpenSearch coverage.** Compare existing vector-store integration
tests with index/search/repository/relations and fraud-knowledge contracts.
Distinguish DynamoDB-backed vector-store coverage from OpenSearch coverage.
Done when each gap names the actual service and adapter involved.

**5.2 Test OpenSearch lifecycle.** With unique document IDs, test ingest/search,
update (old/new terms), idempotent index setup, and cascade deletion including
relations. Use adapter-supported refresh behavior, not arbitrary sleeps. Done
when assertions query OpenSearch and cleanup touches only test-owned data.

**5.3 Audit MinIO coverage.** Retention tests do not prove upload/read behavior.
Compare current tests with object adapter and CSV repository methods; identify
missing byte round-trip, delete, and duplicate-key semantics.

**5.4 Test MinIO lifecycle.** Test byte-identical upload/read, a file large
enough to exercise multipart behavior if applicable, delete idempotency, and
actual duplicate-key semantics. Use unique object prefixes and cleanup on
failure. Done when tests run against MinIO and document overwrite/reject
behavior.

### 6. HTTP load scenarios

**6.1 Audit existing Locust coverage.** Inspect `tests/stress/locustfile.py`
and current targets before choosing to extend Locust or add k6. Record auth,
seed data, cleanup, and whether traffic goes through nginx. Do not keep two tools
for identical scenarios without a reason.

**6.2 Make safe, repeatable fixtures.** Provide disposable alert/operation IDs,
reset/cleanup, configurable host/users/rate/duration, and a request budget.
Defaults must not target production. Done when short local runs are repeatable
without manually finding IDs or mutating shared business data.

**6.3 Measure baselines.** Run each selected profile against rebuilt local
stack through nginx at `http://localhost`; save summaries with service/machine
context and repeat to estimate normal variance. Set thresholds from evidence
before making them gating. Done when the rationale and run are reproducible.

**6.4 Add endpoint profiles.** Add action ramp, async-operation polling, and
escalation burst after fixtures are safe. Count expected business conflicts
separately from transport/server errors. Done when a headless target fails on
threshold regression and writes timestamped results.

### 7. Concurrent-write correctness

**7.1 Define race invariants.** Inspect conditional writes/transactions for
actions, context updates, and reconciliation. Specify win/conflict/retry/merge
behavior before asserting it. Use disposable DynamoDB Local resources. Done
when each case has an explicit invariant.

**7.2 Race alert actions.** Seed one alert, concurrently invoke valid actions,
then re-read from DynamoDB. Assert a valid final transition and documented
loser outcomes, with no torn or silently overwritten state. Repeat runs to
check stability.

**7.3 Race context updates.** Concurrently update one snapshot through the
real persistence path. Assert every contribution is present or conflicts and
retries follow the documented contract. Done when in-process serialization
cannot hide a lost update.

**7.4 Burst queue dispatch.** After task 4, enqueue a configurable batch (start
small and increase), track each task to terminal state with a finite deadline,
and report IDs stuck pending/running. Done when all owned tasks are accounted
for and test data/messages are cleaned up.

### 8. CI and completion evidence

**8.1 Decide CI policy.** Check Jenkins Docker/Compose capability and runtime;
choose PR, scheduled, or merge-to-main execution separately for focused
integration and heavier broker/load suites. Do not gate on unstable load
thresholds. Done when CI invokes documented Make targets.

**8.2 Publish run guide.** Update `tests/README.md` with startup, target
commands, env vars, cleanup, expected duration, and troubleshooting. Link the
coverage matrix and identify suites excluded from default `make test`. Done
when an unfamiliar developer can run a focused group and stop only resources
it started.

**8.3 Record evidence per change.** Run required lint, architecture and
relevant unit tests for code changes, plus focused integration against the real
service. For behavior changes, follow the repo's Playwright E2E requirement
through nginx at `http://localhost`; adapter tests do not replace it when
user-facing behavior changed. Record commands/outcomes. If infrastructure
blocks a required run, name the blocker and leave that task incomplete.

## Recommended execution order

1. Inventory and conventions (0.1–0.3).
2. DynamoDB coverage matrix and missing repository cases (1.1–1.4).
3. OpenSearch/MinIO audits and service-level gaps (5.1–5.4); these can proceed
   independently after harness conventions are set.
4. Verify workflow contract and add workflow cases (3.1–3.5); build broker
   harness and queue cases (4.1–4.4).
5. Expand API coverage by router (2.1–2.4), reusing adapter coverage and
   separating enqueue from execution semantics.
6. Add concurrency cases (7.1–7.4) once persistence and queue contracts are
   known.
7. Add load profiles (6.1–6.4) only after safe fixtures exist and baseline
   latency has been measured.
8. Decide CI scheduling and maintain docs/evidence (8.1–8.3) as slices land.
