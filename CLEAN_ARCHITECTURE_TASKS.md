# Clean Architecture Remediation — Task List

Generated from `CLEAN_ARCHITECTURE_BACKLOG.md` (assessment date 2026-08-21).
Line numbers below were re-verified against the working tree on 2026-09-03;
several files have grown since the assessment (`alert_review_workflow.py`
705 lines, `configuration_port.py` 557 lines, `configurations_router.py`
551 lines, `schemas.py` 922 lines) — re-check line numbers again before
editing, this list will drift too.

Ordered per backlog's "Recommended delivery order". Each task = one
concrete edit. Check off in place; don't renumber.

---

## Phase 1 — CA-001 + CA-010 (unblock everything else)

### CA-001 — Remove LangChain from domain layer

- [ ] Decide: is `AbstractPersistenceUnitOfWork`
      (`src/domain/persistence/__init__.py`) used anywhere? Re-run:
      `grep -rn "AbstractPersistenceUnitOfWork\|domain.persistence" src/ tests/`
      (backlog found zero consumers — confirm still zero).
  - [ ] If still unused: `rm -r src/domain/persistence/`.
  - [ ] If it turns out to be used: move the file to
        `src/infrastructure/persistence/langchain/unit_of_work.py`
        (or similar existing LangChain adapter dir), keep the LangChain
        imports there, and define a project-owned port in
        `src/application/ports/` if application code needs to call it.
- [ ] After deletion, verify:
      `python -c "import src.domain"` and every submodule import cleanly
      without `langchain`/`langchain_core` installed (or grep confirm no
      import remains): `grep -rn "^import\|^from" src/domain/ | grep -v "^src/domain.*: *from __future__\|from typing\|import abc\|import enum\|import dataclasses\|import uuid\|from datetime"`.

### CA-010 — Architecture fitness tests (do this right after CA-001, before other CA work, so nothing regresses)

- [ ] Add `import-linter` (or hand-rolled AST test) to
      `deploy/requirements/pyproject.toml` dev deps.
- [ ] New test file `tests/test_architecture/test_import_boundaries.py`:
  - [ ] Rule 1: no file under `src/domain/` imports anything outside
        stdlib + `src.domain.*`.
  - [ ] Rule 2: no file under `src/application/` imports `src.infrastructure`.
  - [ ] Rule 3: no file outside `src/infrastructure/entrypoint/worker/`
        imports `src.infrastructure.entrypoint.worker.*` (this rule will
        fail today — see CA-004 — leave it added-but-`xfail` until CA-004
        lands, then flip to enforced).
  - [ ] Rule 4: `src/domain` and `src/application` contain no
        `fastapi`, `boto3`, `celery`, `opensearch`, `langchain`,
        `pydantic`, or `opentelemetry` imports (drop the `pydantic`
        exemption only after confirming — grep first,
        `application/dtos` may currently use `@dataclass` not pydantic,
        confirm before asserting).
- [ ] New test `tests/test_architecture/test_composition_smoke.py`:
  - [ ] Import `src.infrastructure.entrypoint.api.fastapi_app` and call
        `create_app()`, assert it does not raise.
  - [ ] For each task in `src/infrastructure/entrypoint/worker/celery/tasks.py`,
        assert the module imports without raising (catches broken inline
        composition).
- [ ] Wire this test file to run first in CI (before slower integration
      tests) — check `.gitlab-ci.yml` / `Makefile` test target ordering,
      add a fast `make test-architecture` target if none exists.

---

## Phase 2 — CA-002 + CA-003 + CA-004 (worker/workflow migration, do together)

### CA-002 — Move fraud-review workflow policy into application layer

File: `src/infrastructure/workflows/celery/alert_review_workflow.py` (705 lines).

- [ ] Read `LINEAR_STEPS` tuple (line 79) and
      `class AlertReviewWorkflowRunner` (line 90) fully before touching —
      this is the highest-risk file in the backlog.
- [ ] Create `src/application/use_cases/alerts/run_alert_review_workflow.py`
      with `RunAlertReviewWorkflowUseCase`. Constructor takes ports for:
      alert repo, workflow execution repo, each of the 7 step
      use-cases/executors, escalation dispatcher
      (`self._escalation = get_analyst_escalation_dispatcher()` at line 96
      — replace the factory call with constructor injection), status
      reporting.
- [ ] Move the retry/escalation policy at lines ~139-215
      (`for step_name in LINEAR_STEPS` loop, `_escalate_to_analyst` at
      line 215) into the new use case as plain methods — no Celery
      imports.
- [ ] Move the adversarial feedback-loop policy: `_effective_max_feedback_iterations`
      (line 509), `_needs_classification_feedback` (line 689), and the
      while-loop at lines 311-344 that increments `context["feedback_iterations"]`
      and raises when `AdversarialFeedbackLimitExceededError` (line 346)
      — this exception currently lives in infrastructure, move its
      definition to `src/application/use_cases/alerts/run_alert_review_workflow.py`
      or a new `src/application/errors.py` per CA-007.
- [ ] Move each step runner (`_run_pre_process` line 363,
      `_run_profiling` line 420, `_run_classification` line 518,
      `_run_adversarial` line 548, `_run_analyst` line 577,
      `_run_executor` line 595, `_run_post_process` line 633) into the
      use case as calls to injected step-use-case ports — these
      currently call `_execute_placeholder_step` (line 647), keep the
      placeholder behavior for now (see CLAUDE.md: steps are still
      placeholder logic, not in scope to implement real step logic here).
- [ ] Replace raw `context: dict[str, Any]` threaded through all of the
      above with a typed dataclass (e.g. `WorkflowRunState`) — define it
      in `src/application/dtos/` or promote to
      `src/domain/alerts/` if CA-005 lands first for this bounded
      context.
- [ ] After the move, `alert_review_workflow.py` (staying under
      `infrastructure/workflows/celery/`) should shrink to: Celery task
      decorator, deserialize input, call
      `RunAlertReviewWorkflowUseCase.execute(...)`, serialize output,
      apply Celery retry (`self.retry(...)`) based on the use case's
      returned/raised outcome.
- [ ] Move tests: any existing feedback-loop/escalation test currently
      under `tests/test_infrastructure/test_workflows/` (grep for
      `feedback_iterations\|AdversarialFeedbackLimitExceededError` under
      `tests/`) → `tests/test_application/test_use_cases/test_run_alert_review_workflow.py`,
      rewritten against in-memory fakes per CLAUDE.md testing convention
      (no Celery, no monkeypatching factories).

### CA-003 — Complete worker composition root, thin out tasks.py

File: `src/infrastructure/entrypoint/worker/celery/tasks.py` (276 lines),
factories: `src/infrastructure/workflows/celery/factories.py`.

- [ ] Line 75: `repository = DynamoAsyncOperationRepository()` → replace
      with `get_async_operation_repository()` from
      `async_operation_factory.py` (the factory already exists — this is
      just a missed call site, not new code).
- [ ] Lines 98-99: `ReconcileAsyncOperationsUseCase(repository=DynamoAsyncOperationRepository(), ...)`
      → add `get_reconcile_async_operations_use_case()` to
      `src/infrastructure/workflows/celery/factories.py` (check —
      `async_operation_factory.py` line 108 already has
      `get_reconcile_async_operations_use_case()`; if that's the API-side
      factory under `entrypoint/api/factories/`, do NOT import it into
      the worker per CLAUDE.md — duplicate a worker-owned version in
      `workflows/celery/factories.py` instead).
- [ ] Line 166: `EscalateAlertToAnalystUseCase(...)` inline → add
      `get_escalate_alert_to_analyst_use_case()` to worker factories.
- [ ] Line 194: `DocumentAnalystDecisionUseCase(...)` inline → add
      `get_document_analyst_decision_use_case()` to worker factories.
- [ ] Line 222: `ExecuteAlertActionUseCase(...)` inline → add
      `get_execute_alert_action_use_case()` to worker factories.
- [ ] Lines 245-248: `AnalyzeDatasetUseCase(dataset_repository=MinioCsvDatasetRepository(get_dataset_object_storage()), sample_repository=DynamoDatasetSampleRepository(), summary_repository=DynamoDatasetSummaryRepository())`
      inline → add `get_analyze_dataset_use_case()` to worker factories,
      cache the object-storage client the same way
      `get_dataset_object_storage()` already does.
- [ ] After all of the above, `tasks.py` should contain: `@app.task`
      decorators, deserialization of task args, one factory call, one
      use-case `.execute(...)` call, serialization of result, retry
      logic. No `Dynamo*(`, `Minio*(`, or `*UseCase(` constructor calls
      left in the file — verify with:
      `grep -n "Dynamo\|Minio\|UseCase(" src/infrastructure/entrypoint/worker/celery/tasks.py`
      (should only match imports, not calls).
- [ ] Add one focused test per task handler under
      `tests/test_infrastructure/test_worker/` using an injected fake
      use case (per CLAUDE.md testing convention — hand-written
      in-memory fake, not `unittest.mock`).

### CA-004 — Stop adapters importing worker entrypoint

Files confirmed still importing `entrypoint.worker.*`:
`src/infrastructure/queues/celery/inspector.py`,
`dispatcher.py`, `dataset_analysis_dispatcher.py`,
`analyst_decision_documenter_dispatcher.py`,
`alert_action_dispatcher.py`, `analyst_escalation_dispatcher.py`,
`analyst_capacity_import_status_reader.py`,
`analyst_capacity_import_dispatcher.py`,
`src/infrastructure/workflows/celery/executor.py` — 9 files, more than
the 4 the backlog cited; grep again right before starting since the
list already grew.

- [ ] Create `src/infrastructure/queues/celery/app.py` (or reuse an
      existing neutral Celery app module if `grep -rn "Celery(" src/infrastructure`
      shows one) holding just the `Celery(...)` client/app instance, no
      task registration.
- [ ] In each of the 9 files above: replace
      `from src.infrastructure.entrypoint.worker... import <task_fn>`
      + `<task_fn>.delay(...)` with
      `celery_app.send_task("<stable.task.name>", args=..., kwargs=...)`
      using the neutral app from the previous step. Get each task's
      registered name from its `@app.task(name=...)` decorator in
      `tasks.py` (add explicit `name=` to each task if not already set —
      implicit names break on module path changes).
- [ ] Task registration (the actual `@app.task def ...` functions) stays
      exclusively in `src/infrastructure/entrypoint/worker/celery/tasks.py`.
- [ ] Add one test asserting each dispatcher's task-name string matches
      an actually-registered task name in `tasks.py` (string-contract
      test, not an import) — this is the "tested contract" the
      acceptance criteria asks for.
- [ ] Flip the CA-010 Rule 3 test from `xfail` to enforced; confirm it
      passes.
- [ ] Add the smoke test the acceptance criteria names: import every API
      router module and assert `sys.modules` contains no
      `src.infrastructure.entrypoint.worker` entry afterward.

---

## Phase 3 — CA-005 (incremental domain migration, start with alert/workflow)

Domain currently: `src/domain/__init__.py` (6 lines),
`src/domain/configurations/exceptions.py` (20 lines),
`src/domain/alerts/exceptions.py` (27 lines) — no entity/state files yet.
Application: `src/application/ports/` has 38 port files; several mix
entities with contracts.

- [ ] **Alerts first** (needed for CA-002 anyway):
  - [ ] New `src/domain/alerts/entities.py`: move `AlertRecord`,
        `AlertStatus` out of `src/application/ports/alert_port.py`
        (49 lines total — the whole file is small, read it fully before
        splitting).
  - [ ] Leave `AlertRepository` Protocol in `alert_port.py`, importing
        `AlertRecord`/`AlertStatus` from the new domain module.
  - [ ] Grep every consumer of `from src.application.ports.alert_port import AlertRecord`
        (and `AlertStatus`) and repoint to
        `from src.domain.alerts.entities import AlertRecord, AlertStatus`:
        `grep -rln "ports.alert_port import.*AlertRecord\|ports.alert_port import.*AlertStatus" src/ tests/`.
- [ ] **Workflow next**: same split for
      `src/application/ports/workflow_port.py` (124 lines) →
      `src/domain/alerts/workflow_entities.py` (or
      `src/domain/workflows/entities.py` if workflows deserve their own
      bounded package — decide based on whether workflow state is
      alert-specific only; current code suggests yes, keep it under
      `domain/alerts/` unless another bounded context needs
      `WorkflowExecutionRecord`/`WorkflowStatus` independently).
- [ ] **Configuration** (largest, do last, most consumers):
      `src/application/ports/configuration_port.py` is now 557 lines
      (grew since backlog's 349-line reference — multi-segment configs +
      channel library work landed since). Read the whole file before
      planning the split; do not reuse the backlog's old line numbers.
  - [ ] New `src/domain/configurations/entities.py` for the stable
        object graph and enums; keep `ConfigurationRepository` Protocol
        in the port file.
  - [ ] This is the highest-blast-radius split (backlog: "avoid a
        single repository-wide rename") — grep consumer count first:
        `grep -rln "ports.configuration_port import" src/ tests/ | wc -l`
        and budget the task accordingly; consider splitting into its own
        follow-up sub-list rather than doing it inline with this pass.
- [ ] Skip test runs / fraud knowledge / operations capacity /
      auth splits until Phase 5 (CA-009 may delete auth/session
      entirely — don't do domain work on code that might be deleted).
- [ ] Add domain tests for whatever moves: state-transition/invariant
      tests under `tests/test_domain/` for each entity now living there.

---

## Phase 4 — CA-006 + CA-007 (opportunistic, alongside each bounded-context migration in Phase 3)

### CA-006 — Remove persistence/queue details from application contracts

- [ ] `src/application/use_cases/alerts/start_alert_test_workflow.py`
      lines 32-39: `MAX_ALERT_PAYLOAD_BYTES = 380_000` with a comment
      explicitly citing "DynamoDB hard-caps a single item at 400KB".
      Move the constant + comment to
      `src/infrastructure/persistence/database/dynamodb/` (co-locate
      with `DynamoAlertRepository`), expose a technology-neutral
      capability like `AlertRepository.max_payload_bytes` or a
      `PayloadTooLargeError` raised by the repository adapter instead of
      pre-checked in the use case. Domain error
      `AlertPayloadTooLargeError` (`src/domain/alerts/exceptions.py:14-26`,
      confirmed still names DynamoDB in its docstring/message at line 14
      and line 25) — reword to be storage-neutral ("exceeds the
      configured storage limit"), keep the exception type, just drop the
      vendor name from the message.
- [ ] `src/application/ports/fraud_knowledge_port.py` line 83:
      docstring says `"""Value doubles as the OpenSearch search_pipeline id."""`
      and line 108 passes `pipeline: SearchPipeline` — introduce a
      technology-neutral enum (e.g. `SearchStrategy`) in the port/domain,
      map `SearchStrategy → OpenSearch pipeline id` inside
      `src/infrastructure/persistence/database/opensearch/` (or wherever
      the OpenSearch adapter for this port lives — locate with
      `grep -rln "fraud_knowledge_port" src/infrastructure/`).
- [ ] `src/application/ports/configuration_port.py`: re-check for
      DynamoDB round-trip shaping (backlog cited old line 306-309; file
      is now 557 lines, re-grep:
      `grep -n "dynamo\|Dynamo\|item.size\|400.*KB\|409" src/application/ports/configuration_port.py`
      before editing).
- [ ] Re-check `analyst_review_alert_dtos.py` and
      `post_process_alert_dtos.py` (old refs: lines 34-37 and 22-23) for
      DynamoDB/Celery-shaped fields; move any serialization-specific
      shaping into infrastructure mappers.

### CA-007 — Normalize error ownership

- [ ] `src/domain/__init__.py` line 1: confirm `DomainException` base
      class exists; check whether `src/domain/alerts/exceptions.py` and
      `src/domain/configurations/exceptions.py` actually inherit from it
      or from bare `Exception` — fix inheritance if not.
- [ ] Move use-case-local error classes out of individual modules into
      a shared `src/application/errors.py` with explicit categories
      (e.g. `NotFoundError`, `ConflictError`, `ValidationError`,
      `OrchestrationError`). Known offenders to re-grep (backlog refs
      may have shifted): `activate_configuration.py`,
      `dataset_sampling.py`, `update_tag.py` — confirm each still
      defines its own exception class with
      `grep -n "^class.*Error" src/application/use_cases/**/*.py`.
- [ ] `AdversarialFeedbackLimitExceededError` — currently in
      `alert_review_workflow.py` line 346 (see CA-002 task above, this
      is the same move, don't do it twice).
- [ ] Add centralized FastAPI exception handlers in
      `src/infrastructure/entrypoint/api/fastapi_app.py` for each new
      application error category (`@app.exception_handler(...)`).
- [ ] `tests/test_infrastructure/test_entrypoint/test_runs_router.py`
      line ~68 (re-grep, backlog line may have shifted) — replace broad
      `except ValueError:` in the router with catches of the new typed
      application errors.
- [ ] Add HTTP-mapping tests covering retryable / validation / not-found
      / conflict / unexpected error → correct status code, and a
      matching Celery-retry-classification test in the worker entrypoint.

---

## Phase 5 — CA-008 + CA-009 (factory + surface cleanup)

### CA-008 — Keep factories limited to composition

File: `src/infrastructure/entrypoint/api/factories/alert_factory.py`.

- [ ] Line 25: `class DeferredWorkflowExecutor(WorkflowExecutor):` defined
      inline in the factory → move to
      `src/infrastructure/workflows/celery/deferred_executor.py` (or
      similar adapter module alongside the real executor), import it
      into the factory.
- [ ] Line 60: `async_operation_repository=DynamoAsyncOperationRepository()`
      inside `get_start_alert_test_workflow_use_case()` bypasses the
      existing `get_async_operation_repository()` singleton factory in
      `async_operation_factory.py` line 55 — replace with a call to that
      factory function.
- [ ] `src/infrastructure/entrypoint/api/factories/async_operation_factory.py`:
  - [ ] Line 36: `class DeferredAsyncExecutor(AsyncExecutor):` → move to
        an adapter module under
        `src/infrastructure/queues/celery/` (or wherever the real
        `AsyncExecutor` implementation lives).
  - [ ] Line 43: `class DeferredAsyncExecutionInspector(AsyncExecutionInspector):`
        → same move, co-locate with the real inspector adapter.
- [ ] Grep for concrete-type return annotations on factory functions
      (`-> Dynamo\w+` instead of `-> \w+Repository`/`-> \w+Port`) across
      `src/infrastructure/entrypoint/api/factories/` and
      `src/infrastructure/workflows/celery/factories.py`; change to the
      port/ABC type unless a caller genuinely needs a concrete-only
      method.
- [ ] Add a short doc comment (one line, top of
      `src/infrastructure/entrypoint/api/factories/__init__.py` or a
      `factories/README` only if truly needed) stating the one caching
      convention: `@lru_cache` for stateless singletons, fresh instance
      per call for use cases — skip this if CLAUDE.md already states it
      clearly enough (it does — probably skip, don't duplicate docs).

### CA-009 — Decide and clean up orphaned capabilities

- [ ] Confirmed still zero consumers of
      `application/dtos/audit_dtos.py`, `application/dtos/auth_dtos.py`,
      `application/dtos/session_dtos.py`,
      `application/ports/auth_port.py`,
      `application/ports/session_port.py`
      (re-verified via grep this session — no hits outside their own
      definition files). Bring this to the user/team for a decision:
      delete, or mark planned with an owner + milestone. **Don't delete
      unilaterally — ask first**, this is a scope decision per
      CLAUDE.md's own note that `audit_port.py` "is an unrelated, older
      concept" worth asking about before merging/removing.
- [ ] `src/persistence/database/dynamodb/manager.py` line ~135 (re-grep,
      confirm still creates an audit table): decide whether to keep
      table creation gated behind the same decision as `audit_port.py`
      above — don't remove the table without the same sign-off.
- [ ] `fraud_knowledge_factory.py` composes list/search/related/ingest/
      update/delete use cases but `fastapi_app.py` (confirmed: routers
      registered are async_operations, alerts, analyst_capacity,
      configurations, datasets, flag_library, health,
      marcacion_catalog, modus_operandi_library,
      resolution_method_catalog, channel_library,
      similar_case_library, tag_catalog, taxonomy_library, test_runs —
      **no fraud-knowledge router**) registers none of them. Confirm
      with the user whether fraud-knowledge is meant to stay
      configuration-internal (called only from
      `activate_configuration.py`) or needs a public router — this
      determines whether CA-009's fix here is "wire it" or "document
      it as internal-only", both are valid, just needs a decision.
- [ ] Once decisions land, update CLAUDE.md's architecture notes to
      match (it already flags the stale `audit_port.py` reference —
      fix that pointer once the decision is made).

---

## Phase 6 — CA-011 + CA-012 (opportunistic hardening, do last)

### CA-011 — Inject time/identity generation

- [ ] Grep current call sites (backlog list may be incomplete/shifted):
      `grep -rln "datetime.now()\|datetime.utcnow()\|uuid4()" src/application/use_cases/`
- [ ] Add `src/application/ports/clock_port.py` (`Clock` ABC, one method
      `now() -> datetime`) and `src/application/ports/id_generator_port.py`
      (`IdGenerator` ABC, one method `new_id() -> str`) — only for the
      **state-creating** use cases the grep above surfaces where replay/
      idempotency matters (async-operation creation, alert-workflow
      start, configuration creation, dataset upload/analysis, test-run
      start, tag creation — per backlog); skip read-only use cases.
- [ ] System adapters: `src/infrastructure/time/system_clock.py`
      (`datetime.now(timezone.utc)`),
      `src/infrastructure/identity/uuid_generator.py` (`uuid.uuid4()`).
- [ ] Wire both into API factories and worker factories per the
      existing `@lru_cache` singleton convention.
- [ ] Rewrite affected use-case tests to assert exact injected
      timestamp/id instead of monkeypatching stdlib.

### CA-012 — Reduce entrypoint mapping concentration

Files confirmed still oversized:
`src/infrastructure/entrypoint/api/routers/configurations_router.py`
(551 lines, was 455 at assessment — grew further),
`src/infrastructure/entrypoint/api/schemas.py`
(922 lines, was 521 at assessment — grew further). Both have grown
since the backlog was written; re-read fully before splitting, don't
trust old line-range citations here at all.

- [ ] Split `schemas.py` by API capability into
      `src/infrastructure/entrypoint/api/schemas/` package: e.g.
      `configurations.py`, `alerts.py`, `datasets.py`, `test_runs.py`,
      etc. — mirror the router filenames under
      `entrypoint/api/routers/` for 1:1 naming.
- [ ] Extract request/domain/response mapping functions out of
      `configurations_router.py` into a new
      `src/infrastructure/entrypoint/api/mappers/configurations_mapper.py`
      (or `.../routers/configurations_mapper.py`, match whatever pattern
      other routers already use, grep first:
      `find src/infrastructure/entrypoint/api -iname "*mapper*"`).
- [ ] Router file after extraction: HTTP input handling, `Depends()`
      use-case invocation, calling mapper functions, response/error
      selection — no inline nested-dict-building mapping logic left.
- [ ] Add mapper round-trip tests (domain → schema → domain) covering
      nested configuration structures, under
      `tests/test_infrastructure/test_entrypoint/`.

---

## Notes for whoever picks this up

- Every file-size/line-number citation above was re-verified against
  the tree on 2026-09-03, but this codebase is under active
  development (3 feature commits landed in the days before this list
  was generated, all touching `configuration_port.py` and related
  files) — re-grep before trusting a line number more than a few days
  old.
- Phase boundaries follow the backlog's own recommended order; phases
  are sequential dependencies (Phase 2 needs Phase 1's boundary tests
  in place to catch regressions; Phase 3's alert/workflow domain split
  is easiest right after Phase 2 touches the same files).
- CA-005 (configuration split) and CA-009 (orphan capability decision)
  both explicitly require a human decision before code changes — don't
  auto-execute those two, surface them first.
