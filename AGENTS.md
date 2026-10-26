# AGENTS.md

Architecture and conventions for this repo live in [CLAUDE.md](CLAUDE.md) —
read it before adding files. Rules every agent must follow:

- Frontend and browser E2E clients reach this API through the same-origin
  `/api/...` path proxied by nginx. Do not direct those clients to `localhost`
  with an API port or to `127.*`; use the configured proxy/location.

- Hexagonal layout: `application/` never imports `infrastructure/`; adapters
  are wired in factory functions, never inline in use cases, routers or tasks.
- Commits: `DEMLGENAIF-<n> <type>(<scope>): <lowercase message>`, no AI
  co-author trailer, never push.

- Every feature or behavior change must update the relevant Playwright E2E
  coverage and run it against the rebuilt local stack through nginx at
  `http://localhost` (port 80). The app is served at `/`, and browser API
  traffic must use the same-origin `/api/...` proxy. E2E tests must load real
  data through the API; do not mock or fulfill API requests in browser E2E.
  A change is not complete until the relevant E2E passes. If environment
  dependencies block the run, report the blocker and leave the work explicitly
  incomplete.

- The `frontend_mockup-web-1` container on port 80 is the expected local
  frontend, not evidence of another session owning the port. Manage it through
  the Make targets: `make frontend` builds and starts the sibling frontend;
  `make local-docker-run` starts the backend stack and frontend;
  `make local-docker-down` stops both while preserving volumes. The frontend
  repo also provides `make down` to stop its Compose project. Serialize E2E
  runs with `/tmp/aria-e2e.lock`; do not wait for the default frontend container
  to disappear before starting a run.

- Before intensive agent-pipeline E2E runs, inspect available host/container
  CPU and memory, current worker usage, and the worker service's configured
  concurrency. Choose a safe worker replica count from those measurements,
  leaving at least 20% memory headroom; then start/scale the test workers from
  the CLI via `LOCAL_DOCKER_TEST_WORKERS=<count> make local-docker-run` (or the
  corresponding Compose `--scale` command). Do not recreate or scale workers
  while a test is actively processing jobs. The local baseline measured on
  2026-10-22 was 15 CPUs and 7.75 GiB RAM; three total test-worker replicas
  were the conservative setting for H9/H11. Re-measure on each machine/run
  rather than assuming that count is universally safe.

## Always run before finishing a change

```bash
make lint                # ruff + mypy ratchet (.lint-baseline.json must not grow)
make lint-baseline       # only after fixing errors: lowers the baseline; never commit a raised one
make test-architecture   # AST fitness tests (tests/test_architecture/)
GENAI_ENVIRONMENT=test pytest   # tests for the code you touched
make test-api-contracts  # when frontend API routes/methods or backend routes change
make e2e-all-local       # full real Playwright suite through nginx localhost:80
make e2e-observability   # focused observability flows through local nginx
```

For Celery task changes, also run
`GENAI_ENVIRONMENT=test pytest tests/test_infrastructure/test_entrypoint/test_celery_task_signature_contracts.py`
and the task's focused behavior tests. For endpoint deprecation, consult
`python scripts/report_api_endpoint_usage.py --help`; zero frontend references
or zero traffic in one time window is not sufficient evidence for deletion.

Jenkins runs `make lint` and `make test-architecture` on every build
(`Lint` and `Architecture` stages in the `Jenkinsfile`).
