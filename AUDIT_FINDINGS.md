# Audit findings — dead code, architecture, inconsistencies

Generated 2026-08-09 via general-purpose agent audit against `CLAUDE.md`'s
stated conventions. Findings and resolutions are tracked below. Format:
`file:line — what's wrong — why it matters — suggested fix`. Check items off
as they're resolved.

## 1. Dead code

> Update 2026-08-09: everything below fixed in `15efb63 chore: remove dead
> auth/session/audit/opensearch code and unused config vars`. New leftover
> found during recheck: `src/application/dtos/audit_dtos.py` survived that
> commit — port/use-cases/adapter all deleted, dtos file wasn't, zero
> importers now. Same fix: delete it too.

- [x] **`src/infrastructure/persistence/search_engine/opensearch/`** (5
  files, 531 lines) — entire module is dead and unbuildable. Nothing under
  `src/` or `tests/` imports it, and its deps (`langchain_community`,
  `opensearchpy`, `requests_aws4auth`) aren't declared in either
  `pyproject.toml`. Copy-paste leftover from the sibling GenAI project, same
  origin as the known-dead `PHOENIX_*` vars. Also has two independent bugs
  if ever imported: `manager.py:19` unused import of `genai_config`;
  `manager.py:96` / `pipelines.py:95` both do `except Exception as e:` and
  never use `e`.
  **Fix:** delete the whole directory. Re-add later scoped to a real
  port/adapter if OpenSearch is actually needed.

- [x] **`src/application/use_cases/auth/*.py`,
  `src/application/use_cases/session/*.py`,
  `src/application/use_cases/audit/*.py`** (8 files: `logout.py`,
  `oauth_callback.py`, `get_current_user.py`, `read_session_state.py`,
  `write_session_state.py`, `delete_session_state.py`,
  `create_audit_log.py`, `list_audit_logs.py`) — orphaned **and broken**.
  They import via `from application....` instead of `from src.application....`
  (`ModuleNotFoundError` if ever exercised). No router, factory, or test
  touches them. `application/ports/auth_port.py` and
  `application/ports/session_port.py` have zero concrete adapters anywhere
  under `infrastructure/`.
  **Fix:** delete (ports, dtos, use cases), or if this is planned work, fix
  the import prefix now so it doesn't bite whoever picks it up next.

- [x] **`application/ports/audit_port.py` vs
  `infrastructure/persistence/database/dynamodb/repositories/audit_log_repository.py`**
  — the "adapter" doesn't implement the port. Port declares
  `create(audit_log) -> AuditLogRecord` / `list_by_conversation(...)`;
  the infra class declares `write(tipo, accion, entidad_tipo, entidad_id, ...)`
  / `list_recent(...)` — different names, different signatures. Combined
  with the broken auth/session/audit use cases above, this port is 100%
  unreachable today.
  **Fix:** retrofit the DynamoDB class to match the Protocol, or delete both
  sides.

- [x] **`src/application/dtos/audit_dtos.py`** — leftover from the
  auth/session/audit deletion above; port, use cases, and the mismatched
  DynamoDB adapter were all deleted but this dtos file wasn't. **(found
  during 2026-08-09 recheck, not in the original audit)** Deleted with the
  orphaned DTO cleanup on 2026-10-12; `rg --files src` confirms the file is
  gone.

- [x] **`src/infrastructure/core/system.py:run_async()`** (98 lines) — zero
  callers (`run_async_operation` in `tasks.py` is a different, unrelated
  symbol — substring collision, not a real reference). Docstring name-checks
  Celery prefork workers / LangChain / httpx cleanup, suggesting it was
  meant to be wired into `tasks.py` and never was.
  **Fix:** delete, or wire it into the Celery task entrypoints it was
  written for.

- [x] **`src/infrastructure/core/config.py:3`** — unused import
  `typing.Optional` (ruff F401). Trivial.

- [x] **`Config` class — ~55 of 102 fields have zero readers anywhere in
  `src/`** outside `config.py` itself. CLAUDE.md already flags `PHOENIX_*`;
  this is the same problem at much larger scale, inherited wholesale from
  the sibling GenAI project:
  - RAG/embedding/search block: `SEARCH_TYPE`, `SIMILITARY_ST_SEARCH_TYPE`,
    `SIMILITARY_ST_SEARCH_K`, `SIMILITARY_ST_SCORE`, `MMR_DIVERSITY_LAMDA`,
    `MMR_FETCH_K`, `SEARCH_K`, `PROXY_NG`, `TIKTOKEN_CACHE_DIR`,
    `TIKTOKEN_ENCODING`, `RAG_EVALUATION_MODEL_NAME`,
    `DEFAULT_EMBEDDING_MODEL_NAME`, `DEFAULT_LLM_MODEL_NAME`,
    `ROUTER_LLM_MODEL_NAME`, `VISION_MODEL_NAME`,
    `SNIPPET_CHUNK_SIZE*`/`SNIPPET_CHUNK_OVERLAP*` (char + token variants),
    `INSTRUCTIONS`, `TEMPERATURE`, `MAX_TOKENS`,
    `DOCUMENT_ASSESSMENT_LLM_MAX_TOKENS`, `KNOWLEDGE_AGENT_TIMEOUT`,
    `KNOWLEDGE_AGENT_MAX_ITERATIONS`, `OPENAI_TIMEOUT`, `OPENAI_MAX_RETRIES`
  - `OPENSEARCH_*` (9 vars) — only read by the now-dead opensearch module
  - `RDS_PSQL_*` (5 vars)
  - `LANGGRAPH_COMPILE_DEBUG`, `DYNAMO_AUTH_SESSIONS_TABLE_NAME`,
    `DYNAMO_CHAT_SESSIONS_TABLE_NAME`, `SESSION_COOKIE_MAX_AGE`,
    `SECURITY_ENABLED`, `ADMIN_TOKEN`, `ALLOWED_ROLES`, `ISSUER`, `JWKS_UR`,
    `AUDIENCE`, `OIDC_TOKEN_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`,
    `JWKS_CACHE_TTL` — these correspond to the dead auth/session slice
    above; likely *unstarted* work rather than pure debris, worth a
    decision rather than a blind delete
  - `NAUTILUS`, `COPILOT_ENABLED`, `COPILOT_PROACTIVE`,
    `COPILOT_SEMANTIC_SEARCH`, `COPILOT_REVIEW_MODE`,
    `LLM_CONCURRENCY_QUESTION`, `NEW_COMPLETION_API_MODELS`
  - `GENAI_OTEL_EXPORTER_KINESIS_STREAM*`,
    `GENAI_OTEL_EXPORTER_OTLP_STREAM_OBFUSCATE_FIELDS` — unread by
    `tracer.py`/`monitoring.py` despite the OTEL-looking name; easy to
    mistake as live
  **Fix:** bulk-delete the RAG/OpenSearch/RDS/Copilot/tiktoken block; keep
  or explicitly ticket the auth/security block since it maps to real (if
  currently broken) use cases.

## 2. Architecture violations

**Clean overall** — worth recording as a baseline, not a to-do:

- Zero `application/` → `infrastructure/` imports (`grep` confirmed empty).
- `llm_unit_of_work_port.py` / `monitoring_port.py` correctly follow the ABC
  single-behavior shape, self-contained, no duplicate factories.
- Celery inline-construction pattern followed consistently across
  `tasks.py`, `dispatcher.py`, `inspector.py`, `alert_review_workflow.py`.
- All 11 port files self-contained (dataclasses/enums colocated), except
  the `audit_port.py` shape-mismatch noted under Dead Code above.

One gap worth tracking, not a violation:

- [x] **`get_llm_unit_of_work_factory()` and `get_monitoring()` are wired
  nowhere.** Both factories are correctly implemented under
  `infrastructure/llm/langchain/__init__.py` and
  `infrastructure/monitoring/opentelemetry/__init__.py`, but no router, use
  case, or Celery task calls either one yet. The adapters built this
  session are currently inert — nothing in the request path produces a
  trace or an LLM call. Matches CLAUDE.md's note that migrating the 7
  `LINEAR_STEPS` into real use cases composing these ports is "planned but
  not done."
  **Fix:** wire these into the first real workflow step that needs them
  (or into `entrypoint/api/factories/` if exposed via API first).
  **Rechecked 2026-08-09: still unfixed**, zero callers of either factory
  besides their own `__init__.py` definitions.
  **Resolved (verified 2026-10-12):** ~35 callers - `workflows/celery/factories.py`,
  `simulator/celery/factories.py` and five API factories.

## 3. Inconsistencies / weak spots

- [x] **`infrastructure/workflows/celery/alert_review_workflow.py`** —
  confirmed still placeholder, matches CLAUDE.md. `_execute_placeholder_step()`
  returns hardcoded stub dicts for all 7 `LINEAR_STEPS`. No change since
  CLAUDE.md was written.
  **Rechecked 2026-08-09: still unfixed.**
  **Resolved (verified 2026-10-12):** `_execute_placeholder_step` is now only a
  dispatcher to real `_run_*` steps backed by use cases via factories.

- [x] **`infrastructure/entrypoint/worker/celery/tasks.py:run_async_operation`**
  (path moved from `infrastructure/queues/celery/tasks.py` by
  `4970d8f refactor(worker): move celery app/tasks under
  entrypoint/worker/celery` — content unchanged) — also placeholder, but
  **not** documented in CLAUDE.md (new finding). Ignores
  `operation.operation_type` entirely and unconditionally marks any
  dispatched async operation `SUCCEEDED` with a canned message. Any real
  generic async-operation feature routed through `POST /async-operations`
  today silently no-ops instead of doing work.
  **Resolved (verified 2026-10-13):** the task checks operation type and
  marks unsupported generic operations failed instead of reporting a
  canned success; registered-but-unimplemented handlers raise
  `NotImplementedError`.

- [x] **`AuditLogRepository.write()` / `list_recent()` swallow all
  `ClientError`s silently** — moot per the original note ("moot today since
  `audit_port` is dead"), and now resolved outright: the whole
  `audit_log_repository.py` file was deleted in `15efb63` along with
  `audit_port.py`. Nothing left to fix. One straggler remains from the same
  cleanup — see `audit_dtos.py` under §1.

**Checked clean, no action needed:**

- `infrastructure/llm/langchain/` vs `infrastructure/monitoring/opentelemetry/`
  — structurally symmetric (both: `__init__.py` with single
  `@lru_cache(maxsize=1)` factory, one adapter file implementing the ABC,
  reads `genai_config` directly). No unexplained divergence.
- No singular/plural directory drift beyond the already-deleted `queue/`
  shim — only `queues/`, `workflows/` exist under `infrastructure/`.
- No `unittest.mock` usage anywhere in `tests/`; hand-written in-memory
  fakes throughout, matches CLAUDE.md convention. No shared `conftest.py`.
- No `AlertRecord` subclass currently violates the no-default-after-default
  MRO footgun CLAUDE.md warns about.
