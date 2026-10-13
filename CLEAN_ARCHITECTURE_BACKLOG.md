# Clean Architecture Assessment and Remediation Backlog

Assessment date: 2026-08-21  
Scope: current `src/` tree, API and Celery entrypoints, composition factories,
adapters, and architecture-related tests. The assessment includes the current
working tree, including uncommitted changes present at the time of review.

> **Status tracking:** This assessment and scorecard record the 2026-08-21
> baseline and are not current evidence. The live checklist is
> `CLEAN_ARCHITECTURE_TASKS.md`; CA status lines are being updated as changes
> are verified. Re-audit the scorecard before using it as a statement of the
> current architecture.

## Executive verdict

The project has a recognizable clean/hexagonal architecture skeleton, but it
is **not yet fully compliant** with clean architecture.

- **Application dependency direction: mostly compliant.** No application
  module imports `src.infrastructure`; use cases generally depend on ports and
  receive collaborators through constructors.
- **Domain layer: not compliant or complete.** It leaves most business records,
  states, and policies inside `application/ports` or infrastructure workflow
  code.
- **Infrastructure adapters: mostly well placed.** DynamoDB, OpenSearch,
  Celery, MinIO/S3, LangChain, and OpenTelemetry implementations live under
  `infrastructure` and usually implement application-owned ports.
- **FastAPI entrypoint and factories: mostly compliant.** `create_app()` owns
  router registration and lifecycle setup, routers receive use cases through
  `Depends`, and factories perform most API composition.
- **Celery entrypoint and factories: not fully compliant.** Task composition
  has improved, but some handlers still construct dependencies inline. The
  fraud-review workflow still owns business orchestration inside
  `infrastructure` and resolves dependencies through factory calls.

Overall status: **partially implemented clean architecture; remediation is
required before calling the architecture clean/hexagonal without qualification.**

## Scorecard

| Area | Status | Evidence |
|---|---|---|
| `domain` is framework/vendor independent | Fail | `src/domain/persistence/__init__.py:5-6` imports LangChain |
| `domain` owns core business model and rules | Fail | Most records/enums are in `src/application/ports`; workflow policy is in `src/infrastructure/workflows/celery/alert_review_workflow.py` |
| `application` does not depend on `infrastructure` | Pass | Static import scan found no such imports |
| Use cases depend on ports | Pass with exceptions | Constructor injection is common across `src/application/use_cases` |
| Infrastructure implements inward-owned ports | Pass | DynamoDB, OpenSearch, Celery, LLM, storage, and monitoring adapters import application ports |
| FastAPI is a thin delivery mechanism | Mostly pass | `fastapi_app.py:44-77`; routers use `Depends` factories |
| API factories are the API composition root | Mostly pass | `src/infrastructure/entrypoint/api/factories/` |
| Celery tasks are thin delivery adapters | Fail | `tasks.py:72`, `tasks.py:95-98`, `tasks.py:156-159`, `tasks.py:184-189`, `tasks.py:212-215`, `tasks.py:235-239` |
| Worker has a complete composition root | Fail | Worker factories cover workflow steps, while several task-specific graphs are assembled inline |
| Dependency rules are automatically enforced | Fail | No architecture/import-boundary tests exist |

## Target dependency rule

```text
domain <- application <- infrastructure/entrypoint
   ^            ^                |
   |            +--- ports <-----+--- adapters
   +--- entities/value objects
```

Allowed dependencies point inward. Entrypoints and factories may know every
outer implementation needed for composition. Domain and application code must
not know FastAPI, Celery, DynamoDB, OpenSearch, LangChain, MinIO/S3, or
OpenTelemetry implementation details.

## Priority definitions

- **P0:** release blocker or immediate correctness/security risk.
- **P1:** major architecture boundary violation with high change cost if left
  in place.
- **P2:** important consistency, maintainability, or testability issue.
- **P3:** incremental hardening and cleanup.

No P0 clean-architecture issue was identified in this review.

## Backlog

### CA-001 - Remove LangChain from the domain layer

**Priority:** P1  
**Status:** [x] Done (2026-10-12, `1477d44`; `src/domain/persistence/` removed, enforced by `test_domain_is_framework_free`)

**Evidence**

- `src/domain/persistence/__init__.py:5-6` imports `BaseRetriever` and
  `Document` from LangChain.
- `AbstractPersistenceUnitOfWork` is not consumed anywhere else in `src/` or
  `tests/`.

**Problem**

The innermost layer depends directly on a replaceable vendor framework. Even
an import of `src.domain.persistence` requires LangChain to be installed.

**Work**

- Delete the unused abstraction if it is obsolete; otherwise move the
  LangChain-specific contract to an infrastructure adapter.
- If conceptual/technical search is a current business capability, define an
  application-owned port using project-owned request/result types.
- Keep the domain layer limited to standard-library and project-domain imports.

**Acceptance criteria**

- Importing every `src.domain` module succeeds without third-party packages.
- No domain file imports `langchain`, `boto3`, `celery`, `fastapi`,
  `opensearch`, `pydantic`, or OpenTelemetry.
- An architecture test enforces the rule.

### CA-002 - Move fraud-review workflow policy into the application layer

**Priority:** P1  
**Status:** [ ] In progress planning; implementation not started (verified 2026-10-13)

**Evidence**

- `alert_review_workflow.py:68-76` defines the business step order.
- `alert_review_workflow.py:79-87` resolves repositories and dispatchers from
  infrastructure factories.
- `alert_review_workflow.py:89-200` owns workflow state transitions, failure
  policy, escalation rules, and completion behavior.
- `alert_review_workflow.py:292-329` owns the adversarial feedback-loop policy.
- `alert_review_workflow.py:332-335` defines a business failure in
  infrastructure.

**Problem**

The most important business orchestration is implemented as a Celery-specific
infrastructure service. It cannot be reused by another delivery mechanism
without depending on infrastructure, and tests must monkeypatch composition
factories rather than inject dependencies explicitly.

**Work**

- Introduce an application use case/service such as
  `RunAlertReviewWorkflowUseCase`.
- Inject repositories, step executors/use cases, status reporting, escalation,
  documentation, and action dispatch ports through its constructor.
- Move step sequencing, feedback limits, status transitions, and terminal
  outcome rules into application/domain code.
- Leave Celery retry metadata and task serialization in the worker entrypoint.
- Replace the raw `dict[str, Any]` context with typed application-owned state
  or explicit step input/output composition.

**Acceptance criteria**

- The entire workflow can run in an application test with in-memory ports and
  no import from `src.infrastructure`.
- The Celery task only deserializes input, invokes the application use case,
  serializes output, and applies Celery retry behavior.
- Feedback-loop and escalation tests move to `tests/test_application`.
- No application workflow rule mentions Celery.

### CA-003 - Make the worker composition root complete and tasks thin

**Priority:** P1  
**Status:** [ ] Not started

**Evidence**

- `tasks.py:72` constructs `DynamoAsyncOperationRepository` directly.
- `tasks.py:95-98` assembles reconciliation inline.
- `tasks.py:156-159`, `184-189`, and `212-215` assemble alert use cases
  inline.
- `tasks.py:235-239` assembles dataset analysis inline.
- Existing `workflows/celery/factories.py` only composes the main workflow
  dependencies and six step use cases.

**Problem**

Composition is split between factories, task functions, adapter package
initializers, and the workflow runner. This makes dependency selection
inconsistent and task functions difficult to unit test without importing
vendor SDKs.

**Work**

- Add worker factory functions for every task-level application service.
- Place the worker composition root under the worker entrypoint, or define and
  document one canonical worker factory location.
- Cache stateless adapters where appropriate and return fresh use-case
  instances.
- Pass the composed service into a small task handler function that can be
  tested without Celery.

**Acceptance criteria**

- No Celery task body calls a concrete `Dynamo*`, `Mock*`, `Minio*`, or
  `*UseCase` constructor.
- Backend selection occurs only in worker factories.
- Each task handler has a focused test using an injected fake use case.
- API factories and worker factories follow the same documented lifecycle
  conventions.

### CA-004 - Stop adapters from importing worker entrypoints

**Priority:** P1  
**Status:** [ ] Partially implemented (2026-10-13): neutral Celery app and
task-name dispatch are in place; verify the registered-name contract and
router smoke-test criteria in `CLEAN_ARCHITECTURE_TASKS.md`.

**Evidence**

- `queues/celery/dispatcher.py:8` imports a task from the worker entrypoint.
- `queues/celery/dataset_analysis_dispatcher.py:6` imports a task from the
  worker entrypoint.
- `workflows/celery/executor.py:8` imports a task from the worker entrypoint.
- Other Celery adapters import the entrypoint-owned app at
  `alert_action_dispatcher.py:9`, `analyst_escalation_dispatcher.py:9`,
  `analyst_decision_documenter_dispatcher.py:10`, and `inspector.py:12`.
- Comments in the dispatchers explicitly describe avoiding circular imports.

**Problem**

An output adapter should not depend on a delivery entrypoint. The current
direction creates import cycles, couples API-side dispatch adapters to worker
task registration, and causes unrelated workflow imports to load Celery.

**Work**

- Move Celery app/client construction to a neutral Celery infrastructure
  module, or inject a task sender/result backend into adapters from each
  composition root.
- Dispatch by stable task name instead of importing task functions.
- Keep task registration exclusively under the worker entrypoint.

**Acceptance criteria**

- Nothing outside `src/infrastructure/entrypoint/worker` imports
  `entrypoint.worker.*`.
- Importing an adapter does not import the worker task module.
- API dispatch and worker execution still agree on task names through one
  tested contract.
- A smoke test imports all API routers without loading worker tasks.

### CA-005 - Establish a real domain model instead of storing entities in ports

**Priority:** P1  
**Status:** [ ] Not started

**Evidence**

- The complete domain layer has 93 lines, while application has more than
  6,000 lines.
- `application/ports/alert_port.py:10-28` combines alert state/entity types
  with the repository contract.
- `application/ports/workflow_port.py:10-60` combines workflow entities and
  states with persistence contracts.
- `application/ports/configuration_port.py:11-346` contains a large
  configuration object graph and business enums before the repository port at
  line 349.
- Similar entity/port mixing exists for test runs, tags, fraud knowledge,
  operations capacity, and authentication records.

**Problem**

Ports should describe boundaries; they should not be the default home for the
core model. The current layout produces an anemic domain and makes unrelated
adapters import large port modules simply to use business types.

**Work**

- Define bounded domain packages for alerts, workflows, configurations, test
  runs, datasets, and fraud knowledge.
- Move stable entities, value objects, state enums, invariants, and domain
  errors into those packages.
- Keep request/response DTOs in application and repository/service contracts
  in application ports.
- Migrate incrementally by bounded context; avoid a single repository-wide
  rename.

**Acceptance criteria**

- Port modules primarily contain `Protocol`/`ABC` definitions and boundary
  records that truly belong to the integration contract.
- Core state transitions and invariants are exercised by domain tests.
- Application use cases import domain types rather than treating repository
  records as the domain model.
- Infrastructure serialization maps domain types without adding persistence
  concerns to them.

### CA-006 - Remove persistence and queue details from application contracts

**Priority:** P2  
**Status:** [ ] Not started

**Evidence**

- `start_alert_test_workflow.py:31-38` hard-codes a DynamoDB item-size limit in
  an application use case.
- `domain/alerts/exceptions.py:14-26` names DynamoDB in a domain error.
- `fraud_knowledge_port.py:82-87` uses OpenSearch pipeline IDs as application
  enum values.
- `configuration_port.py:306-309` shapes the business object graph around
  DynamoDB round-trip limitations.
- `analyst_review_alert_dtos.py:34-37` and
  `post_process_alert_dtos.py:22-23` shape outputs around DynamoDB/Celery
  serialization constraints.

**Problem**

Replacing DynamoDB, OpenSearch, or Celery would require changes inside domain
or application modules. Serialization and storage-capacity concerns belong at
adapter boundaries unless they represent a technology-neutral product rule.

**Work**

- Express payload limits as an injected product policy or repository
  capability, and map adapter capacity failures to a technology-neutral
  application error.
- Give search strategies technology-neutral values; map them to OpenSearch
  pipeline IDs in the OpenSearch adapter.
- Serialize `datetime`, enums, and nested unions in infrastructure mappers.
- Keep DTO types optimized for use-case meaning rather than transport/storage
  compatibility.

**Acceptance criteria**

- `src/domain` and `src/application` contain no DynamoDB, OpenSearch, MinIO,
  or Celery names in executable contracts or policy definitions.
- Swapping a search or persistence adapter does not change use-case APIs.
- Adapter serialization tests cover all domain/application value types.

### CA-007 - Normalize error ownership and entrypoint translation

**Priority:** P2  
**Status:** [ ] Not started

**Evidence**

- `DomainException` exists at `domain/__init__.py:1` but domain errors inherit
  directly from `Exception`.
- Application errors are defined inside individual use-case modules:
  `activate_configuration.py:14`, `dataset_sampling.py:21`, and
  `update_tag.py:10`.
- A workflow business error is defined in infrastructure at
  `alert_review_workflow.py:332`.
- FastAPI routers translate errors independently and sometimes catch broad
  `ValueError` (`test_runs_router.py:68`).

**Problem**

Error categories do not have a consistent owner or transport mapping. This
couples callers to concrete use-case modules and risks different HTTP behavior
for equivalent failures.

**Work**

- Define domain errors for invariant/business-rule failures and application
  errors for orchestration/not-found/conflict outcomes.
- Make exceptions inherit from explicit base categories.
- Register centralized FastAPI exception handlers for shared error categories;
  keep endpoint-specific mapping only where response semantics differ.
- Keep Celery retry classification in the worker entrypoint, based on stable
  application error categories.

**Acceptance criteria**

- No business error is declared in `infrastructure`.
- Routers do not catch undifferentiated `ValueError` for expected outcomes.
- HTTP and Celery mappings have tests covering retryable, validation,
  not-found, conflict, and unexpected errors.

### CA-008 - Keep factories limited to composition

**Priority:** P2  
**Status:** [ ] Not started

**Evidence**

- `alert_factory.py:25-30` defines `DeferredWorkflowExecutor` inside a factory.
- `async_operation_factory.py:36-51` defines two deferred adapter
  implementations inside a factory.
- `alert_factory.py:60` bypasses `get_async_operation_repository()` and
  constructs `DynamoAsyncOperationRepository` directly.
- Several repository factory return annotations expose concrete Dynamo types
  instead of application ports.

**Problem**

Factories are becoming implementation modules and have multiple construction
paths for the same dependency. That weakens backend substitution and makes
lifecycle rules harder to reason about.

**Work**

- Move deferred implementations to dedicated infrastructure adapter modules.
- Define one factory function per port/backend selection.
- Reuse repository factories consistently within use-case factories.
- Prefer port return types at composition boundaries unless callers require a
  concrete-only capability.

**Acceptance criteria**

- Factory files contain imports, backend selection, caching, and object-graph
  assembly only.
- No concrete dependency used by a use-case factory is constructed outside its
  canonical adapter factory.
- Tests clear/override cached factories in one documented way.

### CA-009 - Decide and clean up unexposed or orphaned capabilities

**Priority:** P2  
**Status:** [ ] Partially implemented (2026-10-13): fraud-knowledge exposure
decision is resolved as internal-only with no dedicated API/router. Audit
log repository/factory/schema and table ownership still require a decision.

**Evidence**

- `application/dtos/audit_dtos.py`, `application/dtos/auth_dtos.py`,
  `application/dtos/session_dtos.py`, `application/ports/auth_port.py`, and
  `application/ports/session_port.py` have no source consumers. **Deleted 2026-10-12.**
- Dynamo table initialization still creates an audit table at
  `persistence/database/dynamodb/manager.py:135`, but there is no current
  audit port/repository/use case/entrypoint flow.
- `fraud_knowledge_factory.py` composes list/search/related/ingest/update/delete
  use cases. **Decision 2026-10-13:** fraud-knowledge is internal to the
  worker and API; it does not need a dedicated public router/API.

**Problem**

Dead scaffolding obscures the supported architecture, while composed but
unregistered capabilities create an incomplete entrypoint surface.

**Work**

- For each orphan, mark it as planned with an owner and target milestone, wire
  it end to end, or delete it.
- Preserve fraud-knowledge as internal-only; do not add a dedicated router.
- Remove database tables and configuration that no active capability owns.
- Update `CLAUDE.md` after the decision; remove stale references to the
  deleted `application/ports/audit_port.py`.

**Acceptance criteria**

- Every production port and DTO has at least one use-case consumer, or is
  explicitly documented as a planned contract.
- Every factory is reachable from an entrypoint or startup composition path.
- Startup creates only tables owned by active capabilities.
- Architecture documentation matches files that exist.

### CA-010 - Add executable architecture fitness tests

**Priority:** P2  
**Status:** [x] Done (2026-10-12; `tests/test_architecture/`, ratcheted, `make test-architecture`, runs as the Jenkins `Architecture` stage)

**Evidence**

- The test suite has domain, application, and infrastructure behavior tests,
  but no import/dependency-boundary test.
- The documented rule that application never imports infrastructure is only a
  convention.

**Work**

- Add an AST-based test or an import-boundary tool such as `import-linter`.
- Enforce: domain imports only domain/standard library; application may import
  domain/application but not infrastructure; entrypoint modules are not
  imported by adapters; framework imports remain in infrastructure.
- Add a composition smoke test for every registered API router and worker
  task.
- Run these tests in CI before slower integration tests.

**Acceptance criteria**

- Introducing a forbidden import makes CI fail with the offending module
  named in the error.
- The current `domain.persistence` violation is removed before enabling the
  rule.
- API and worker composition smoke tests run under their declared Python 3.11
  dependency sets.

### CA-011 - Inject time and identity generation into state-creating use cases

**Priority:** P3  
**Status:** [ ] Not started

**Evidence**

- Multiple application use cases call `datetime.now()` and `uuid4()` directly,
  including async-operation creation, alert-workflow start, configuration
  creation, dataset upload/analysis, test-run start, and tag creation.

**Problem**

This is not a dependency-direction violation, but it makes application tests
less deterministic and complicates replay/idempotency behavior in retrying
worker flows.

**Work**

- Introduce small application-owned `Clock` and `IdGenerator` ports only where
  deterministic replay or retry behavior matters.
- Supply system implementations from API/worker factories.
- Avoid applying the abstraction mechanically to read-only use cases.

**Acceptance criteria**

- State-creating workflow tests assert exact timestamps and IDs without
  monkeypatching standard-library functions.
- Retried commands can reuse command-provided identities where idempotency is
  required.

### CA-012 - Reduce entrypoint mapping concentration

**Priority:** P3  
**Status:** [ ] Not started

**Evidence**

- `entrypoint/api/routers/configurations_router.py` is 455 lines and contains
  endpoint handlers plus extensive request/domain/response mapping.
- `entrypoint/api/schemas.py` is 521 lines and contains schemas for several
  unrelated API capabilities.

**Problem**

The code is in the correct outer layer, but concentrated transport mapping
makes router changes high-risk and obscures handler behavior.

**Work**

- Split schemas and mappers by API capability.
- Keep routers focused on HTTP input, use-case invocation, and response/error
  selection.
- Do not move Pydantic models or HTTP concerns inward.

**Acceptance criteria**

- Configuration endpoints delegate mapping to entrypoint-owned mapper modules.
- Mapper round-trip tests cover nested configuration structures.
- No Pydantic or FastAPI import is introduced into application/domain.

## Recommended delivery order

1. Complete CA-001 and establish CA-010 boundary tests so further work cannot
   add new inward dependency violations.
2. Implement CA-002, CA-003, and CA-004 together as the worker/workflow
   architecture migration.
3. Migrate domain types incrementally through CA-005, starting with alert and
   workflow state used by CA-002.
4. Address CA-006 and CA-007 while each bounded context is migrated.
5. Complete factory and surface cleanup through CA-008 and CA-009.
6. Apply CA-011 and CA-012 opportunistically after the main boundaries are
   stable.

## Verification performed

- Static source inventory and internal import scan across `src/domain`,
  `src/application`, and `src/infrastructure`.
- Entrypoint, router, factory, worker-task, workflow, port, and representative
  adapter review.
- `GENAI_ENVIRONMENT=test pytest tests/test_domain tests/test_application -q`:
  **136 passed** with 11 pytest collection warnings caused by domain types
  whose names begin with `Test`.
- Full `GENAI_ENVIRONMENT=test pytest -q` did not complete in the current local
  interpreter because the active Python 3.13 environment lacks declared
  runtime dependencies `celery` and `langchain_aws`. The project declares
  Python 3.11 and includes those packages in its Poetry manifests, so this is
  recorded as a verification-environment limitation rather than an
  architecture failure.

