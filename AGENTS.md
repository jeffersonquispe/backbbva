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

## Always run before finishing a change

```bash
make lint                # ruff + mypy ratchet (.lint-baseline.json must not grow)
make lint-baseline       # only after fixing errors: lowers the baseline; never commit a raised one
make test-architecture   # AST fitness tests (tests/test_architecture/)
GENAI_ENVIRONMENT=test pytest   # tests for the code you touched
make e2e-all-local       # full real Playwright suite through nginx localhost:80
make e2e-observability   # focused observability flows through local nginx
```

Jenkins runs `make lint` and `make test-architecture` on every build
(`Lint` and `Architecture` stages in the `Jenkinsfile`).
