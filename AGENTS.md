# AGENTS.md

Architecture and conventions for this repo live in [CLAUDE.md](CLAUDE.md) —
read it before adding files. Rules every agent must follow:

- Hexagonal layout: `application/` never imports `infrastructure/`; adapters
  are wired in factory functions, never inline in use cases, routers or tasks.
- Commits: `DEMLGENAIF-<n> <type>(<scope>): <lowercase message>`, no AI
  co-author trailer, never push.

## Always run before finishing a change

```bash
make lint                # ruff + mypy ratchet (.lint-baseline.json must not grow)
make lint-baseline       # only after fixing errors: lowers the baseline; never commit a raised one
make test-architecture   # AST fitness tests (tests/test_architecture/)
GENAI_ENVIRONMENT=test pytest   # tests for the code you touched
```

Jenkins runs `make lint` and `make test-architecture` on every build
(`Lint` and `Architecture` stages in the `Jenkinsfile`).
