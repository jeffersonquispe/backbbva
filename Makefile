# Load variables from .envs/.make if it exists (use -include to not fail if missing)
-include .envs/.make

SHELL := /usr/bin/env bash

# ─── Python runner: use poetry run when available, plain python otherwise ─────
# This allows db-backup/restore commands to work inside Docker containers where
# the venv is already in PATH but poetry is not installed.
PYTHON := $(if $(and $(wildcard pyproject.toml),$(shell command -v poetry 2>/dev/null)),poetry run python,python)

# ─── Container runtime (prefer podman, fall back to docker) ──────────────────
DOCKER := $(or $(shell which docker 2>/dev/null),$(shell which podman 2>/dev/null))

# Validate that all required variables are set
.PHONY: check-vars
check-vars:
	@if [ -z "$(ARTIFACTORY_USER)" ]; then \
		echo "Error: ARTIFACTORY_USER is not set. Please set it in .envs/.make or as environment variable."; \
		exit 1; \
	fi
	@if [ -z "$(ARTIFACTORY_PASSWORD)" ]; then \
		echo "Error: ARTIFACTORY_PASSWORD is not set. Please set it in .envs/.make or as environment variable."; \
		exit 1; \
	fi
	@if [ -z "$(GENAI_ENVIRONMENT)" ]; then \
		echo "Error: GENAI_ENVIRONMENT is not set. Please set it in .envs/.make or as environment variable."; \
		exit 1; \
	fi
	@if [ -z "$(DEBUG)" ]; then \
		echo "Error: DEBUG is not set. Please set it in .envs/.make or as environment variable."; \
		exit 1; \
	fi
	@if [ -z "$(DEBUGPY_PORT)" ]; then \
		echo "Error: DEBUGPY_PORT is not set. Please set it in .envs/.make or as environment variable."; \
		exit 1; \
	fi
	@if [ -z "$(WAIT_FOR_DEBUGGER)" ]; then \
		echo "Error: WAIT_FOR_DEBUGGER is not set. Please set it in .envs/.make or as environment variable."; \
		exit 1; \
	fi

ARTIFACTORY_PYPY_URL := https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@artifactory.globaldevtools.bbva.com/artifactory/api/pypi/gl-ai-genai-python-virtual/simple
PROJECT_NAME ?= aria-api
PROJECT_VERSION ?= local
PIP_CMD := $(shell command -v pip || echo "")
PIP3_CMD := $(shell command -v pip3 || echo "")
POETRY_VERSION := 1.8.5

ifeq ($(PIP_CMD),)
	PIP_COMMAND_FLAG = pip3
else
	PIP_COMMAND_FLAG = pip
endif

# ─── Compose file ──────────────────────────────────────────────────────────────
# Builds from public registries only (see deploy/local/docker/Dockerfile.api)
# — no Artifactory login needed.
_COMPOSE_FILE := deploy/local/docker/docker-compose.yml
_HAS_COMPOSE  := $(shell docker compose version >/dev/null 2>&1 && echo yes)
# Use compose only when: local env + compose file present + docker compose available
USE_COMPOSE   := $(if $(and $(wildcard $(_COMPOSE_FILE)),$(_HAS_COMPOSE),$(filter local,$(GENAI_ENVIRONMENT))),yes,)
_BUILD_DEPS   :=

# ─── Shared build / run arguments ─────────────────────────────────────────────
# Recursive (=) so values re-expand at recipe time with whatever vars are set.
DOCKER_BUILD_ARGS = \
	--build-arg ARTIFACTORY_USER=$(ARTIFACTORY_USER) \
	--build-arg ARTIFACTORY_PASSWORD=$(ARTIFACTORY_PASSWORD) \
	--build-arg GENAI_ENVIRONMENT=$(GENAI_ENVIRONMENT) \
	--build-arg DEBUG=$(or $(DEBUG),false) \
	--build-arg DEBUGPY_PORT=$(or $(DEBUGPY_PORT),5678) \
	--build-arg WAIT_FOR_DEBUGGER=$(or $(WAIT_FOR_DEBUGGER),false)

DOCKER_RUN_ENV = \
	-e AWS_DEFAULT_REGION=local \
	-e GENAI_ENVIRONMENT=$(GENAI_ENVIRONMENT) \
	-e DEBUG=$(or $(DEBUG),false) \
	-e DEBUGPY_PORT=$(or $(DEBUGPY_PORT),5678) \
	-e WAIT_FOR_DEBUGGER=$(or $(WAIT_FOR_DEBUGGER),false)

.DEFAULT_GOAL := help

.PHONY: local-users
local-users:  ## Interactive menu to create/list local-auth users or change a password (API_URL, ARIA_BOOTSTRAP_TOKEN optional).
	@python3 scripts/local_users.py $(if $(API_URL),--api-url $(API_URL))

.PHONY: create-local-user
create-local-user:  ## Interactively create a local-auth user (role picked from a list); no credential is stored.
	@python3 scripts/local_users.py create $(if $(API_URL),--api-url $(API_URL))

.PHONY: list-local-users
list-local-users:  ## List local-auth users (needs the bootstrap token).
	@python3 scripts/local_users.py list $(if $(API_URL),--api-url $(API_URL))

.PHONY: change-local-user-password
change-local-user-password:  ## Pick a local-auth user from a list and set a new password.
	@python3 scripts/local_users.py passwd $(if $(API_URL),--api-url $(API_URL))

OKD_NAMESPACE ?=
OKD_TOOLBOX_DIR := deploy/okd/iac_celery/computation/ops-toolbox

.PHONY: okd-users
okd-users:  ## Run the interactive user manager inside OKD via a throwaway pod. Vars: OKD_NAMESPACE (required), USERS_ACTION (create|list|passwd; default menu)
	@test -n "$(OKD_NAMESPACE)" || { echo "OKD_NAMESPACE is required (oc login first)"; exit 1; }
	@oc -n $(OKD_NAMESPACE) delete pod aria-ops-toolbox --ignore-not-found --wait=true
	@oc -n $(OKD_NAMESPACE) apply -f $(OKD_TOOLBOX_DIR)/serviceaccount.yaml -f $(OKD_TOOLBOX_DIR)/pod.yaml
	@oc -n $(OKD_NAMESPACE) wait --for=condition=Ready pod/aria-ops-toolbox --timeout=180s
	@oc -n $(OKD_NAMESPACE) cp scripts/local_users.py aria-ops-toolbox:/tmp/local_users.py
	@oc -n $(OKD_NAMESPACE) exec -it aria-ops-toolbox -- python3 /tmp/local_users.py $(USERS_ACTION); \
		status=$$?; oc -n $(OKD_NAMESPACE) delete pod aria-ops-toolbox --ignore-not-found --wait=false; exit $$status

.PHONY: refresh-github-token
refresh-github-token:  ## Replace the saved GitHub credential with a classic PAT.
	@set -euo pipefail; \
	branch="$$(git branch --show-current)"; \
	remote="$$(git config --get "branch.$$branch.remote" || printf '%s' origin)"; \
	remote_url="$$(git remote get-url "$$remote")"; \
	case "$$remote_url" in \
		https://*) ;; \
		*) echo "Remote $$remote must use an HTTPS URL (found: $$remote_url)" >&2; exit 2;; \
	esac; \
	host="$${remote_url#https://}"; host="$${host%%/*}"; \
	old_credential="$$(printf 'protocol=https\nhost=%s\n\n' "$$host" | GIT_TERMINAL_PROMPT=0 git credential fill 2>/dev/null || true)"; \
	if [ -n "$$old_credential" ]; then \
		printf '%s\n' "$$old_credential" | git credential reject; \
		echo "Removed the existing credential for $$remote ($$host)."; \
	fi; \
	read -r -p "GitHub username: " username; \
	[ -n "$$username" ] || { echo "Username cannot be empty." >&2; exit 2; }; \
	read -r -s -p "New GitHub classic personal access token: " token; printf '\n'; \
	[ -n "$$token" ] || { echo "Token cannot be empty." >&2; exit 2; }; \
	printf 'protocol=https\nhost=%s\nusername=%s\npassword=%s\n\n' "$$host" "$$username" "$$token" | git credential approve; \
	unset token; \
	echo "Saved the new credential for $$username@$$host."

.PHONY: install
install:  ## Install the project in dev mode.
	poetry install
	@echo "Don't forget to run 'make shell' if you got errors."

.PHONY: shell
shell:  ## Open a virtual environment.
	poetry shell

.PHONY: test
test:  ## Run tests and generate coverage report.
	@echo "--- Running tests... ---"
	python -m pytest


.PHONY: test-architecture
test-architecture:  ## Fast AST check of the CLAUDE.md layer/DI/env/observability rules (ratcheted baseline, no services needed).
	GENAI_ENVIRONMENT=test python -m pytest tests/test_architecture -q


.PHONY: test-integration-reservations
test-integration-reservations:  ## Run resource-reservation tests (voicebot slots / analyst locks) against the running local DynamoDB. Vars: DYNAMO_PORT(8002)
	GENAI_ENVIRONMENT=test DYNAMO_ENDPOINT=http://localhost:$${DYNAMO_PORT:-8002} DYNAMO_REGION_NAME=us-east-1 \
		DYNAMO_ACCESS_KEY=dummy DYNAMO_SECRET_KEY=dummy \
		python -m pytest -m docker_integration tests/test_integration/test_resource_reservations

.PHONY: test-integration-metrics
test-integration-metrics:  ## Run metrics snapshot/rollup tests (transaction, retry, version race, TTL, created_day index) against the running local DynamoDB. Vars: DYNAMO_PORT(8002)
	GENAI_ENVIRONMENT=test DYNAMO_ENDPOINT=http://localhost:$${DYNAMO_PORT:-8002} DYNAMO_REGION_NAME=us-east-1 \
		DYNAMO_ACCESS_KEY=dummy DYNAMO_SECRET_KEY=dummy \
		python -m pytest -m docker_integration tests/test_integration/test_metrics_rollups

.PHONY: test-integration-retention
test-integration-retention:  ## Run the object-storage retention e2e against the running local MinIO. Vars: MINIO_PORT(9000), OBJECT_STORAGE_ACCESS_KEY(dummy), OBJECT_STORAGE_SECRET_KEY(dummy123)
	GENAI_ENVIRONMENT=test OBJECT_STORAGE_ENDPOINT=http://localhost:$${MINIO_PORT:-9000} \
		OBJECT_STORAGE_ACCESS_KEY=$${OBJECT_STORAGE_ACCESS_KEY:-dummy} \
		OBJECT_STORAGE_SECRET_KEY=$${OBJECT_STORAGE_SECRET_KEY:-dummy123} \
		python -m pytest -m docker_integration tests/test_integration/test_object_storage_retention

.PHONY: metrics-backfill
metrics-backfill:  ## Rebuild metrics snapshots + rollups for alerts of FROM..TO (Bogota days, inclusive) that have none. Idempotent. Vars: FROM, TO (YYYY-MM-DD, required), DYNAMO_PORT(8002), GENAI_ENVIRONMENT(local)
	@if [ -z "$(FROM)" ] || [ -z "$(TO)" ]; then \
		echo "ERROR: usage: make metrics-backfill FROM=YYYY-MM-DD TO=YYYY-MM-DD"; \
		exit 1; \
	fi
	GENAI_ENVIRONMENT=$${GENAI_ENVIRONMENT:-local} API_V0_STR=$${API_V0_STR:-/api/v0} \
		DYNAMO_ENDPOINT=http://localhost:$${DYNAMO_PORT:-8002} DYNAMO_REGION_NAME=us-east-1 \
		DYNAMO_ACCESS_KEY=dummy DYNAMO_SECRET_KEY=dummy \
		python -m src.infrastructure.entrypoint.worker.metrics_backfill --from $(FROM) --to $(TO)

# Q3/A4 load test: a THROWAWAY DynamoDB Local on its own port (table names
# have no prefix, so never point these at the stack's 8002).
LOADTEST_DYNAMO_PORT ?= 8012
LOADTEST_ENV = GENAI_ENVIRONMENT=$${GENAI_ENVIRONMENT:-local} API_V0_STR=$${API_V0_STR:-/api/v0} \
	DYNAMO_ENDPOINT=http://localhost:$(LOADTEST_DYNAMO_PORT) DYNAMO_REGION_NAME=us-east-1 \
	DYNAMO_ACCESS_KEY=dummy DYNAMO_SECRET_KEY=dummy

.PHONY: metrics-loadtest-up
metrics-loadtest-up:  ## Start a throwaway DynamoDB Local (container aria-dynamodb-loadtest) for the metrics load test. Vars: LOADTEST_DYNAMO_PORT(8012)
	docker run -d --rm --name aria-dynamodb-loadtest -p $(LOADTEST_DYNAMO_PORT):8000 \
		amazon/dynamodb-local:latest -jar DynamoDBLocal.jar -sharedDb

.PHONY: metrics-loadtest-down
metrics-loadtest-down:  ## Remove the throwaway load-test DynamoDB Local and all its data.
	docker rm -f aria-dynamodb-loadtest

.PHONY: metrics-synthetic-load
metrics-synthetic-load:  ## Q3: synthetic alerts + every metrics event through the real writers, into the load-test DynamoDB. Vars: DAYS(90), PER_DAY(1500), TECH_SAMPLE(0.1), WORKERS(1; more processes hit DynamoDB Local lock timeouts)
	$(LOADTEST_ENV) python -m src.infrastructure.entrypoint.worker.metrics_synthetic_load \
		--days $${DAYS:-90} --per-day $${PER_DAY:-1500} --tech-sample $${TECH_SAMPLE:-0.1} --workers $${WORKERS:-1}

.PHONY: metrics-query-bench
metrics-query-bench:  ## A4: p50/p95 of /metrics/overview|agent|technical for 24h..1y, with/without filters, against the load-test DynamoDB. Vars: RUNS(15)
	$(LOADTEST_ENV) python -m src.infrastructure.entrypoint.api.metrics_query_bench --runs $${RUNS:-15}

.PHONY: test-e2e-simulation
test-e2e-simulation:  ## Run the simulator lifecycle/tick/dispatch e2e test against local DynamoDB. Vars: DYNAMO_PORT(8002)
	GENAI_ENVIRONMENT=test DYNAMO_ENDPOINT=http://localhost:$${DYNAMO_PORT:-8002} DYNAMO_REGION_NAME=us-east-1 \
		DYNAMO_ACCESS_KEY=dummy DYNAMO_SECRET_KEY=dummy \
		python -m pytest -m docker_integration tests/test_integration/test_event_simulation


.PHONY: test-unit-vector-store
test-unit-vector-store:  ## Run isolated Vector Store use-case tests (no Docker required).
	GENAI_ENVIRONMENT=test API_V0_STR=/api/v0 python -m pytest \
		tests/test_application/test_use_cases/test_vector_store_instances.py \
		tests/test_application/test_use_cases/test_vector_store_knowledge_graph.py

.PHONY: test-api-vector-store
test-api-vector-store:  ## Run Vector Store HTTP API contract tests (no Docker required).
	GENAI_ENVIRONMENT=test API_V0_STR=/api/v0 python -m pytest \
		tests/test_infrastructure/test_entrypoint/test_vector_store_instances_router.py

.PHONY: test-integration-docker-vector-store
test-integration-docker-vector-store: docker-test-build  ## Run Vector Store tests against Docker DynamoDB Local.
	@$(MAKE) GENAI_ENVIRONMENT=local docker-run
	@$(DOCKER) run --rm --network lupita-data_aria-net \
		-e GENAI_ENVIRONMENT=local -e API_V0_STR=/api/v0 \
		-e DYNAMO_ENDPOINT=http://dynamodb:8000 -e DYNAMO_REGION_NAME=us-east-1 \
		-e DYNAMO_ACCESS_KEY=dummy -e DYNAMO_SECRET_KEY=dummy \
		aria-api-test:$(TEST_IMAGE_TAG) pytest -m docker_integration \
		tests/test_integration/test_vector_store

TEST_IMAGE_TAG ?= test

.PHONY: docker-test-build
docker-test-build:  ## Build the Docker test image (dev deps + tests/, no live services required).
	@$(DOCKER) build -f deploy/local/docker/Dockerfile.test -t aria-api-test:$(TEST_IMAGE_TAG) .

.PHONY: docker-test
docker-test: docker-test-build  ## Run the test suite inside Docker. Vars: PYTEST_ARGS(extra pytest flags)
	@$(DOCKER) run --rm aria-api-test:$(TEST_IMAGE_TAG) pytest $(PYTEST_ARGS)

.PHONY: docker-test-worker-build
docker-test-worker-build:  ## Build the Docker test image with worker (Celery) deps instead of API deps.
	@$(DOCKER) build -f deploy/local/docker/Dockerfile.test.worker -t aria-worker-test:$(TEST_IMAGE_TAG) .

.PHONY: docker-test-worker
docker-test-worker: docker-test-worker-build  ## Run the test suite inside Docker with worker deps (covers infrastructure/workflows, infrastructure/queues/celery). Vars: PYTEST_ARGS(extra pytest flags)
	@$(DOCKER) run --rm aria-worker-test:$(TEST_IMAGE_TAG) pytest --ignore=tests/test_infrastructure/test_entrypoint $(PYTEST_ARGS)

# source $(poetry env info --path)/Scripts/activate

.PHONY: clean
clean:  ## Clean Python cache, build artefacts, and local backup files. Object storage data in containers is NOT touched (use db-prune for that).
	@find ./ -name '*.pyc' -o -name '__pycache__' -o -name 'Thumbs.db' -o -name '*~' -exec rm -rf {} +;
	@rm -rf .cache .pytest_cache .mypy_cache build dist *.egg-info htmlcov .tox/ docs/_build backups/
	@echo "Project cleaned (Python artefacts + local backups removed)."

.PHONY: download-poetry
download-poetry: ## Download poetry from Artifactory.
	@echo "Installing poetry ${POETRY_VERSION} from Artifactory..."
	@$(PIP_COMMAND_FLAG) install poetry==${POETRY_VERSION} --index-url $(ARTIFACTORY_PYPY_URL)
	@echo "Poetry installed at: $$(which poetry)"

# ─── Docker targets ───────────────────────────────────────────────────────────

.PHONY: docker-login
docker-login:  ## Log in to Artifactory container registry.
	@if [ -z "$(ARTIFACTORY_USER)" ] || [ -z "$(ARTIFACTORY_PASSWORD)" ]; then \
		echo "Error: ARTIFACTORY_USER and ARTIFACTORY_PASSWORD must be set"; \
		echo "Please set them in .envs/.make or as environment variables"; \
		exit 1; \
	fi
	@$(DOCKER) login artifactory.globaldevtools.bbva.com:443 \
		-u $(ARTIFACTORY_USER) -p $(ARTIFACTORY_PASSWORD)

.PHONY: docker-build
docker-build: $(_BUILD_DEPS)  ## Build the standalone stack image (compose for local env, direct docker otherwise).
ifeq ($(USE_COMPOSE),yes)
	@echo "Using docker compose -f $(_COMPOSE_FILE) (local + compose file detected)"
	@DEBUG=$(DEBUG) DEBUGPY_PORT=$(DEBUGPY_PORT) WAIT_FOR_DEBUGGER=$(WAIT_FOR_DEBUGGER) \
	GENAI_ENVIRONMENT=$(GENAI_ENVIRONMENT) \
	LUPITA_API_IMAGE_VERSION=$(LUPITA_API_IMAGE_VERSION) \
	LUPITA_WORKER_IMAGE_VERSION=$(LUPITA_WORKER_IMAGE_VERSION) \
	docker compose -p lupita-data -f $(_COMPOSE_FILE) --env-file ./.envs/.make build $(DOCKER_BUILD_ARGS) --no-cache
else
	@echo "Direct docker build (GENAI_ENVIRONMENT=$(GENAI_ENVIRONMENT))"
	@$(DOCKER) build --platform linux/amd64 $(DOCKER_BUILD_ARGS) \
		-f deploy/Dockerfile -t $(PROJECT_NAME):$(PROJECT_VERSION) .
endif

# docker-build-image: build a specific image (api or worker) with a custom name and tag.
#
# Required:
#   TARGET   — which image to build: "api" (uses Dockerfile) or "worker" (uses Dockerfile.worker)
#   IMAGE    — full image name, e.g. myregistry.example.com/lupita-api
#
# Optional:
#   TAG      — image tag (default: PROJECT_VERSION from pyproject.toml)
#   PLATFORM — target platform (default: linux/amd64). Examples: linux/arm64
#   SAVE     — set to "true" to export the image to ./images/ after build
#              filename: lupita-{TARGET}-{TAG}-{platform}.tar
#              e.g.      lupita-api-1.2.3-linux-amd64.tar
#
# Examples:
#   make docker-build-image TARGET=api   IMAGE=myregistry/lupita-api TAG=1.2.3
#   make docker-build-image TARGET=worker IMAGE=myregistry/lupita-worker
#   make docker-build-image TARGET=api   IMAGE=myregistry/lupita-api SAVE=true
#   make docker-build-image TARGET=api   IMAGE=myregistry/lupita-api TAG=latest PLATFORM=linux/arm64 SAVE=true
#   make docker-build-image TARGET=api IMAGE=quay.io/bbva-co/lupita-api-preproduccion TAG=kev-minIO PLATFORM=linux/amd64
#   make docker-build-image TARGET=worker IMAGE=quay.io/bbva-co/lupita-worker-preproduccion TAG=v3 PLATFORM=linux/amd64
.PHONY: docker-build-image
docker-build-image: docker-login  ## Build a single image. Vars: TARGET(api|worker) IMAGE(required) TAG(opt) PLATFORM(opt) SAVE(opt=true)
	@if [ -z "$(TARGET)" ]; then \
		echo "Error: TARGET is required. Use TARGET=api or TARGET=worker"; \
		exit 1; \
	fi; \
	if [ -z "$(IMAGE)" ]; then \
		echo "Error: IMAGE is required. Example: IMAGE=myregistry/lupita-api"; \
		exit 1; \
	fi; \
	if [ "$(TARGET)" = "api" ]; then \
		_DOCKERFILE=deploy/Dockerfile; \
	elif [ "$(TARGET)" = "worker" ]; then \
		_DOCKERFILE=deploy/Dockerfile.worker; \
	else \
		echo "Error: TARGET must be 'api' or 'worker', got '$(TARGET)'"; \
		exit 1; \
	fi; \
	_TAG=$${TAG:-$(PROJECT_VERSION)}; \
	_PLATFORM=$${PLATFORM:-linux/amd64}; \
	_FULL_IMAGE=$(IMAGE):$$_TAG; \
	echo "Building $$_FULL_IMAGE from $$_DOCKERFILE (platform=$$_PLATFORM)"; \
	$(DOCKER) build \
		--platform $$_PLATFORM \
		-f $$_DOCKERFILE \
		$(DOCKER_BUILD_ARGS) \
		-t $$_FULL_IMAGE \
		. && \
	echo "Built: $$_FULL_IMAGE"; \
	if [ "$(SAVE)" = "true" ]; then \
		_PLATFORM_TAG=$$(echo "$$_PLATFORM" | tr '/' '-'); \
		_TAR_NAME="lupita-$(TARGET)-$$_TAG-$$_PLATFORM_TAG.tar"; \
		mkdir -p images; \
		echo "Saving image to images/$$_TAR_NAME ..."; \
		$(DOCKER) save -o "images/$$_TAR_NAME" "$$_FULL_IMAGE" && \
		echo "Saved: images/$$_TAR_NAME"; \
	fi

.PHONY: docker-run
docker-run:  ## Run the standalone stack (compose) or a single container.
ifeq ($(USE_COMPOSE),yes)
	@echo "Running docker compose -f $(_COMPOSE_FILE) up -d (GENAI_ENVIRONMENT=$(GENAI_ENVIRONMENT))"
	@DEBUG=$(DEBUG) DEBUGPY_PORT=$(DEBUGPY_PORT) WAIT_FOR_DEBUGGER=$(WAIT_FOR_DEBUGGER) \
	GENAI_ENVIRONMENT=$(GENAI_ENVIRONMENT) \
	$(DOCKER) compose -p lupita-data -f $(_COMPOSE_FILE) --env-file ./.envs/.make up -d
else
	@$(DOCKER) run --rm --platform linux/amd64 \
		$(DOCKER_RUN_ENV) \
		-p 8000:8000 \
		-p $(or $(DEBUGPY_PORT),5678):$(or $(DEBUGPY_PORT),5678) \
		--name $(PROJECT_NAME) \
		$(PROJECT_NAME):$(PROJECT_VERSION)
endif

.PHONY: docker-down
docker-down:  ## Stop and remove the standalone stack containers.
	@if [ -f "$(_COMPOSE_FILE)" ]; then \
		echo "Bringing down docker compose services ($(_COMPOSE_FILE))..."; \
		$(DOCKER) compose -p lupita-data -f $(_COMPOSE_FILE) --env-file ./.envs/.make down; \
	else \
		echo "Compose file $(_COMPOSE_FILE) not found, nothing to do."; \
	fi

LOCAL_DOCKER_COMPOSE_FILE ?= deploy/local/docker/docker-compose.yml
LOCAL_DOCKER_PROJECT ?= aria-local
LOCAL_DOCKER_ENV ?= local
LOCAL_API_PORT ?= 8000
LOCAL_DYNAMODB_PORT ?= 8002
LOCAL_REDIS_PORT ?= 6379
LOCAL_IMAGE_TAG ?= local

# Sibling repo, not part of this git tree - guard every target below so a
# checkout without it (e.g. CI, a fresh clone) doesn't fail the backend stack.
FRONTEND_DIR ?= ../frontend_mockup

.PHONY: frontend
frontend:  ## Build and run the sibling frontend project from ../frontend.
	@if [ ! -d "$(FRONTEND_DIR)" ]; then \
		echo "Error: $(FRONTEND_DIR) directory does not exist." >&2; \
		exit 1; \
	fi; \
	( cd $(FRONTEND_DIR) && $(MAKE) build && $(MAKE) run )

LOCAL_DOCKER_ENV_FLAGS = \
	GENAI_ENVIRONMENT=$(LOCAL_DOCKER_ENV) \
	LOCAL_API_PORT=$(LOCAL_API_PORT) \
	LOCAL_DYNAMODB_PORT=$(LOCAL_DYNAMODB_PORT) \
	LOCAL_REDIS_PORT=$(LOCAL_REDIS_PORT) \
	LOCAL_IMAGE_TAG=$(LOCAL_IMAGE_TAG)

# Local builds reuse Docker's dependency layers by default. Set
# LOCAL_DOCKER_BUILD_ARGS=--no-cache when a completely clean rebuild is needed.
LOCAL_DOCKER_BUILD_ARGS ?=

.PHONY: local-auth-up
local-auth-up:  ## Start/rebuild only the local API with interactive auth secrets (not stored).
	@set -euo pipefail; \
	read -r -s -p "Secreto de firma JWT: " auth_jwt_secret; printf '\n'; \
	read -r -s -p "Token de aprovisionamiento: " auth_bootstrap_token; printf '\n'; \
	[ -n "$$auth_jwt_secret" ] && [ -n "$$auth_bootstrap_token" ] || { echo "Ambos valores son obligatorios." >&2; exit 1; }; \
	AUTH_JWT_SECRET="$$auth_jwt_secret" AUTH_BOOTSTRAP_TOKEN="$$auth_bootstrap_token" \
	$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		up -d --build api

.PHONY: local-docker-build
local-docker-build:  ## Build local API, worker and MCP images. Vars: LOCAL_DOCKER_ENV, LOCAL_API_PORT, LOCAL_DYNAMODB_PORT, LOCAL_IMAGE_TAG
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api aria-worker-main aria-agent-worker aria-agent-beat aria-worker-training mcp

.PHONY: local-api-build
local-api-build:  ## Build only the local API image from the current backend source.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api

.PHONY: local-worker-refresh
local-worker-refresh:  ## Recreate local alert/test/training workers and MCP from current images.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		up -d --force-recreate aria-worker-main aria-agent-worker aria-agent-beat aria-worker-test aria-worker-training mcp

.PHONY: local-test-queue-purge
local-test-queue-purge:  ## Purge queued test-run tasks after stopping the local test worker.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		up -d --force-recreate aria-worker-test
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		exec -T aria-worker-test python -c "from src.infrastructure.entrypoint.worker.celery.celery_app import app; connection = app.connection_for_write(); channel = connection.channel(); print('Purged queued test tasks:', channel.queue_purge('test')); connection.close()"

.PHONY: local-e2e-logs
local-e2e-logs:  ## Show recent local API and E2E worker logs.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		logs --tail=120 --no-color api aria-worker-main aria-agent-worker aria-agent-beat aria-worker-test

.PHONY: local-worker-stats
local-worker-stats:  ## Show a point-in-time CPU/RAM reading for local worker services.
	@$(DOCKER) stats --no-stream aria-worker-main aria-agent-worker aria-agent-beat aria-worker-training aria-worker-test aria-worker-scheduler aria-worker-simulator

.PHONY: local-docker-run
local-docker-run:  ## Run local Docker API stack + frontend (FRONTEND_DIR, default ../frontend_mockup). LLM/other app config comes from config/$(LOCAL_DOCKER_ENV)/config.cfg, mounted read-only - edit it and re-run this to pick up changes. Vars: LOCAL_DOCKER_ENV, LOCAL_API_PORT, LOCAL_DYNAMODB_PORT, LOCAL_IMAGE_TAG
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		up -d --remove-orphans
	@# config.cfg is a mounted file, not a compose-level env var - `up -d`
	@# alone won't notice its content changed, so always restart the services
	@# services that read it. Cheap (no rebuild, no image pull) and a no-op
	@# on freshly-created containers.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		restart api aria-worker-main aria-agent-worker aria-agent-beat aria-worker-training mcp
	@if [ -d "$(FRONTEND_DIR)" ]; then \
		$(MAKE) -C $(FRONTEND_DIR) run; \
	else \
		echo "FRONTEND_DIR=$(FRONTEND_DIR) not found, skipping frontend."; \
	fi

.PHONY: local-docker-stop
local-docker-stop: local-docker-down  ## Alias for local-docker-down; preserves volumes.

.PHONY: local-docker-down
local-docker-down:  ## Remove local Docker API stack + frontend containers and networks; preserve volumes.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		down
	@if [ -d "$(FRONTEND_DIR)" ]; then \
		$(MAKE) -C $(FRONTEND_DIR) down; \
	else \
		echo "FRONTEND_DIR=$(FRONTEND_DIR) not found, skipping frontend."; \
	fi

# ─── Local observability services in the general local stack ──
OBSERVABILITY_SERVICES := observability-minio observability-minio-init otel-collector tempo loki prometheus grafana

.PHONY: observability-up
observability-up:  ## Start the local observability stack (Grafana at :3000).
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		up -d $(OBSERVABILITY_SERVICES)

.PHONY: observability-down
observability-down:  ## Stop the local observability stack.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		stop $(OBSERVABILITY_SERVICES)

.PHONY: observability-logs
observability-logs:  ## Tail logs for the local observability stack.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		logs -f $(OBSERVABILITY_SERVICES)

# ─── Backup / restore flags ───────────────────────────────────────────────────
# SKIP_OBJECT_STORAGE=1  — omit object storage from backup/restore/prune/drop
# BACKUP_DIR             — target / source directory for backup and restore
# OS_BULK_SIZE           — OpenSearch restore bulk size (lower for low-memory PCs)
# OS_CHECKPOINT_FILE     — Optional restore checkpoint JSON path
# RESUME_OPENSEARCH=1    — Resume OpenSearch restore from checkpoint
_OS_FLAG := $(if $(SKIP_OBJECT_STORAGE),--skip-object-storage,)
_OS_BULK_FLAG := $(if $(OS_BULK_SIZE),--os-bulk-size $(OS_BULK_SIZE),)
_OS_CHECKPOINT_FLAG := $(if $(OS_CHECKPOINT_FILE),--os-checkpoint-file $(OS_CHECKPOINT_FILE),)
_OS_RESUME_FLAG := $(if $(RESUME_OPENSEARCH),--resume-opensearch,)

.PHONY: db-backup
db-backup:  ## Backup DynamoDB + OpenSearch + object storage to ./backups/<timestamp>/ (stack must be running). Var: SKIP_OBJECT_STORAGE=1
	@if [ -n "$(LOCAL_DOCKER_PROJECT)" ] && $(DOCKER) compose -p $(LOCAL_DOCKER_PROJECT) -f $(LOCAL_DOCKER_COMPOSE_FILE) ps --services --filter status=running 2>/dev/null | grep -qx aria-worker-main; then \
		$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose -p $(LOCAL_DOCKER_PROJECT) -f $(LOCAL_DOCKER_COMPOSE_FILE) exec -T aria-worker-main python scripts/db_backup.py backup $(if $(BACKUP_DIR),--dir $(BACKUP_DIR),) $(_OS_FLAG); \
	elif [ -n "$(LOCAL_DOCKER_PROJECT)" ]; then \
		DYNAMO_ENDPOINT=$${DYNAMO_ENDPOINT:-http://localhost:$${LOCAL_DYNAMODB_PORT:-8002}} OBJECT_STORAGE_ENDPOINT=$${OBJECT_STORAGE_ENDPOINT:-http://localhost:$${LOCAL_MINIO_PORT:-9000}} OPENSEARCH_ENDPOINT=$${OPENSEARCH_ENDPOINT:-http://localhost:$${LOCAL_OPENSEARCH_PORT:-9200}} $(PYTHON) scripts/db_backup.py backup $(if $(BACKUP_DIR),--dir $(BACKUP_DIR),) $(_OS_FLAG); \
	else \
		$(PYTHON) scripts/db_backup.py backup $(if $(BACKUP_DIR),--dir $(BACKUP_DIR),) $(_OS_FLAG); \
	fi

.PHONY: db-restore
db-restore:  ## Restore from backup. Vars: BACKUP_DIR(req), SKIP_OBJECT_STORAGE=1, OS_BULK_SIZE=20, OS_CHECKPOINT_FILE=..., RESUME_OPENSEARCH=1
	@if [ -z "$(BACKUP_DIR)" ]; then \
		echo "ERROR: BACKUP_DIR is required. Usage: make db-restore BACKUP_DIR=./backups/<timestamp>"; \
		exit 1; \
	fi
	@if [ -n "$(LOCAL_DOCKER_PROJECT)" ] && $(DOCKER) compose -p $(LOCAL_DOCKER_PROJECT) -f $(LOCAL_DOCKER_COMPOSE_FILE) ps --services --filter status=running 2>/dev/null | grep -qx aria-worker-main; then \
		$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose -p $(LOCAL_DOCKER_PROJECT) -f $(LOCAL_DOCKER_COMPOSE_FILE) exec -T aria-worker-main python scripts/db_backup.py restore --dir $(BACKUP_DIR) $(_OS_FLAG) $(_OS_BULK_FLAG) $(_OS_CHECKPOINT_FLAG) $(_OS_RESUME_FLAG); \
	elif [ -n "$(LOCAL_DOCKER_PROJECT)" ]; then \
		DYNAMO_ENDPOINT=$${DYNAMO_ENDPOINT:-http://localhost:$${LOCAL_DYNAMODB_PORT:-8002}} OBJECT_STORAGE_ENDPOINT=$${OBJECT_STORAGE_ENDPOINT:-http://localhost:$${LOCAL_MINIO_PORT:-9000}} OPENSEARCH_ENDPOINT=$${OPENSEARCH_ENDPOINT:-http://localhost:$${LOCAL_OPENSEARCH_PORT:-9200}} $(PYTHON) scripts/db_backup.py restore --dir $(BACKUP_DIR) $(_OS_FLAG) $(_OS_BULK_FLAG) $(_OS_CHECKPOINT_FLAG) $(_OS_RESUME_FLAG); \
	else \
		$(PYTHON) scripts/db_backup.py restore --dir $(BACKUP_DIR) $(_OS_FLAG) $(_OS_BULK_FLAG) $(_OS_CHECKPOINT_FLAG) $(_OS_RESUME_FLAG); \
	fi

.PHONY: db-backup-list
db-backup-list:  ## List all available backups in ./backups/
	@$(PYTHON) scripts/db_backup.py list

.PHONY: db-drop-tables
db-drop-tables:  ## Drop ALL DynamoDB tables, OpenSearch indices, and object storage bucket (stack must be running). Var: SKIP_OBJECT_STORAGE=1
	@echo "WARNING: this will permanently delete all tables, indices, and object storage bucket."
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ] || (echo "Aborted."; exit 1)
	@$(PYTHON) scripts/db_backup.py drop $(_OS_FLAG)

.PHONY: db-prune
db-prune:  ## Delete all records from DynamoDB, OpenSearch, and object storage (keeps schemas and bucket). Var: SKIP_OBJECT_STORAGE=1
	@echo "WARNING: this will permanently delete all data (schemas, indices, and bucket are preserved)."
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ] || (echo "Aborted."; exit 1)
	@$(PYTHON) scripts/db_backup.py prune $(_OS_FLAG)

.PHONY: e2e-clean
e2e-clean:  ## Destructive: clean E2E data through nginx/API, preserving users and tables.
	@$(MAKE) -C ../frontend_mockup down
	@$(MAKE) -C ../frontend_mockup run
	@E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) E2E_MANAGER_EMAIL=$(E2E_MANAGER_EMAIL) E2E_MANAGER_PASSWORD=$(E2E_MANAGER_PASSWORD) $(PYTHON) scripts/e2e_api_clean.py --yes
	@# API startup restores the local baseline configuration and reference catalogs.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose -p $(LOCAL_DOCKER_PROJECT) -f $(LOCAL_DOCKER_COMPOSE_FILE) restart api aria-worker-main
	@$(MAKE) -C ../frontend_mockup down
	@$(MAKE) -C ../frontend_mockup run

.PHONY: e2e-seed
e2e-seed:  ## Seed the reusable alert-schema E2E baseline through nginx/API.
	@test -n "$(E2E_MANAGER_EMAIL)" -a -n "$(E2E_MANAGER_PASSWORD)" -a -n "$(E2E_RELEASE_MANAGER_EMAIL)" -a -n "$(E2E_RELEASE_MANAGER_PASSWORD)" || (echo "ERROR: set E2E_MANAGER_EMAIL/E2E_MANAGER_PASSWORD/E2E_RELEASE_MANAGER_EMAIL/E2E_RELEASE_MANAGER_PASSWORD"; exit 1)
	@E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		E2E_MANAGER_EMAIL=$(E2E_MANAGER_EMAIL) E2E_MANAGER_PASSWORD=$(E2E_MANAGER_PASSWORD) \
		E2E_RELEASE_MANAGER_EMAIL=$(E2E_RELEASE_MANAGER_EMAIL) E2E_RELEASE_MANAGER_PASSWORD=$(E2E_RELEASE_MANAGER_PASSWORD) \
		$(PYTHON) scripts/e2e_api_seed.py

.PHONY: e2e-presence
e2e-presence:  ## Dispatch and verify today's schema-presence analysis via the local worker and API.
	@test -n "$(E2E_MANAGER_EMAIL)" -a -n "$(E2E_MANAGER_PASSWORD)" || (echo "ERROR: set E2E_MANAGER_EMAIL/E2E_MANAGER_PASSWORD"; exit 1)
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose -p $(LOCAL_DOCKER_PROJECT) -f $(LOCAL_DOCKER_COMPOSE_FILE) \
		exec -T aria-worker-main python -c "from src.infrastructure.entrypoint.worker.celery.celery_app import app; app.send_task('alert_schema.analyze_presence')"
	@E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		E2E_MANAGER_EMAIL=$(E2E_MANAGER_EMAIL) E2E_MANAGER_PASSWORD=$(E2E_MANAGER_PASSWORD) \
		$(PYTHON) scripts/e2e_api_wait_presence.py

.PHONY: e2e-alert-processing
e2e-alert-processing:  ## Run E07 alert intake, real workflow, escalation and analyst resolution through nginx/API.
	@test -n "$(E2E_MANAGER_EMAIL)" -a -n "$(E2E_MANAGER_PASSWORD)" -a -n "$(E2E_FRAUD_ANALYST_EMAIL)" -a -n "$(E2E_FRAUD_ANALYST_PASSWORD)" || (echo "ERROR: set E2E_MANAGER_EMAIL/E2E_MANAGER_PASSWORD/E2E_FRAUD_ANALYST_EMAIL/E2E_FRAUD_ANALYST_PASSWORD"; exit 1)
	@E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		E2E_MANAGER_EMAIL=$(E2E_MANAGER_EMAIL) E2E_MANAGER_PASSWORD=$(E2E_MANAGER_PASSWORD) \
		E2E_FRAUD_ANALYST_EMAIL=$(E2E_FRAUD_ANALYST_EMAIL) E2E_FRAUD_ANALYST_PASSWORD=$(E2E_FRAUD_ANALYST_PASSWORD) \
		E2E_WORKFLOW_TIMEOUT=$(if $(E2E_WORKFLOW_TIMEOUT),$(E2E_WORKFLOW_TIMEOUT),600) \
		$(PYTHON) scripts/e2e_alert_processing_local.py

.PHONY: e2e-fraud-review
e2e-fraud-review:  ## Run E08 fraud marking, correction and audit-history E2E through nginx/API.
	@$(MAKE) -C ../frontend_mockup run
	@E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		$(PYTHON) scripts/e2e_fraud_review_local.py

.PHONY: e2e-observability
e2e-observability:  ## Rebuild API/worker/web and run real dashboards, metrics audit, and TTL cleanup Playwright E2E through nginx.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api aria-worker-main aria-agent-worker aria-agent-beat
	@$(MAKE) -C ../frontend_mockup build
	@$(MAKE) local-docker-run
	@E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		LOCAL_DOCKER_PROJECT=$(LOCAL_DOCKER_PROJECT) \
		LOCAL_DOCKER_ENV=$(LOCAL_DOCKER_ENV) \
		$(PYTHON) scripts/e2e_observability_local.py

.PHONY: e2e-agent-local
e2e-agent-local:  ## Run real assistant/optimizer API and Celery lifecycle E2E through nginx localhost:80.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api aria-worker-main aria-agent-worker aria-agent-beat
	@$(MAKE) local-docker-run
	@E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		LOCAL_DOCKER_PROJECT=$(LOCAL_DOCKER_PROJECT) \
		LOCAL_DOCKER_ENV=$(LOCAL_DOCKER_ENV) \
		LOCAL_DYNAMODB_PORT=$(LOCAL_DYNAMODB_PORT) \
		$(PYTHON) scripts/e2e_agent_local.py

.PHONY: e2e-agent-h9-local
e2e-agent-h9-local:  ## Run the H9 optimizer Playwright flow through nginx localhost:80.
	@set -euo pipefail; \
	lock=/tmp/aria-e2e.lock; \
	while ! mkdir "$$lock" 2>/dev/null; do sleep 2; done; \
	trap 'rmdir "$$lock"' EXIT; \
	$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api aria-agent-worker aria-agent-beat; \
	$(MAKE) local-docker-run; \
	E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
	LOCAL_DOCKER_PROJECT=$(LOCAL_DOCKER_PROJECT) \
	node scripts/e2e_agent_h9_local.mjs

.PHONY: e2e-agent-h10-local
e2e-agent-h10-local:  ## Run H10 specialist selection and verification through nginx localhost:80.
	@$(MAKE) e2e-agent-h9-local

.PHONY: e2e-agent-global-pipeline-local
e2e-agent-global-pipeline-local:  ## Compare READY baseline/candidate over a real reserved final sample through nginx localhost:80.
	@set -euo pipefail; \
	lock=/tmp/aria-e2e.lock; \
	while ! mkdir "$$lock" 2>/dev/null; do sleep 2; done; \
	trap 'rmdir "$$lock"' EXIT; \
	$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api aria-worker-training aria-agent-worker; \
	$(MAKE) local-docker-run; \
	E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
	LOCAL_DOCKER_PROJECT=$(LOCAL_DOCKER_PROJECT) \
	LOCAL_DOCKER_ENV=$(LOCAL_DOCKER_ENV) \
	LOCAL_DYNAMODB_PORT=$(LOCAL_DYNAMODB_PORT) \
	$(PYTHON) scripts/e2e_global_pipeline_local.py

.PHONY: e2e-agent-chat-local
e2e-agent-chat-local:  ## Run real Playwright chat/masking/idempotency E2E through nginx localhost:80.
	@set -euo pipefail; \
	lock=/tmp/aria-e2e.lock; \
	while ! mkdir "$$lock" 2>/dev/null; do sleep 2; done; \
	trap 'rmdir "$$lock"' EXIT; \
	$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api; \
	$(MAKE) local-docker-run; \
	E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
	LOCAL_DOCKER_PROJECT=$(LOCAL_DOCKER_PROJECT) \
	node scripts/e2e_agent_chat_local.mjs

.PHONY: e2e-agent-modus-operandi-local
e2e-agent-modus-operandi-local:  ## Run real Playwright modus operandi draft/confirmation E2E through nginx localhost:80.
	@set -euo pipefail; \
	lock=/tmp/aria-e2e.lock; \
	while ! mkdir "$$lock" 2>/dev/null; do sleep 2; done; \
	trap 'rmdir "$$lock"' EXIT; \
	$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api; \
	$(MAKE) local-docker-run; \
	E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
	LOCAL_DOCKER_PROJECT=$(LOCAL_DOCKER_PROJECT) \
	node scripts/e2e_agent_modus_operandi_local.mjs

.PHONY: e2e-all-local
e2e-all-local:  ## Rebuild the local stack and run the full real-API Playwright E2E suite through nginx localhost:80.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build $(LOCAL_DOCKER_BUILD_ARGS) api aria-worker-main aria-agent-worker aria-agent-beat
	@$(MAKE) -C ../frontend_mockup build
	@CELERY_STUCK_TASK_TIMEOUT_SECONDS=120 $(MAKE) local-docker-run
	@CELERY_STUCK_TASK_TIMEOUT_SECONDS=120 E2E_FULL_SUITE=1 E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		LOCAL_DOCKER_PROJECT=$(LOCAL_DOCKER_PROJECT) \
		LOCAL_DOCKER_ENV=$(LOCAL_DOCKER_ENV) \
		$(PYTHON) scripts/e2e_observability_local.py

.PHONY: e2e-real
e2e-real:  ## Run real E2E from zero (default) or resume at a numbered E2E_FROM checkpoint (1-6).
	@test -n "$(E2E_MANAGER_EMAIL)" -a -n "$(E2E_MANAGER_PASSWORD)" -a -n "$(E2E_RELEASE_MANAGER_EMAIL)" -a -n "$(E2E_RELEASE_MANAGER_PASSWORD)" || (echo "ERROR: set E2E_MANAGER_EMAIL/E2E_MANAGER_PASSWORD/E2E_RELEASE_MANAGER_EMAIL/E2E_RELEASE_MANAGER_PASSWORD"; exit 1)
	@test -z "$(E2E_FROM)" -o "$(E2E_FROM)" = "0" -o -n "$(filter $(E2E_FROM),1 2 3 4 5 6)" || (echo "ERROR: E2E_FROM supports 0 (full clean run) or a checkpoint from 1 to 6"; exit 1)
	@$(MAKE) -C ../frontend_mockup down
	@$(MAKE) -C ../frontend_mockup build
	@$(MAKE) -C ../frontend_mockup run
	@if test -z "$(E2E_FROM)" -o "$(E2E_FROM)" = "0"; then \
		E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) E2E_MANAGER_EMAIL=$(E2E_MANAGER_EMAIL) E2E_MANAGER_PASSWORD=$(E2E_MANAGER_PASSWORD) $(PYTHON) scripts/e2e_api_clean.py --yes && \
		$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose -p $(LOCAL_DOCKER_PROJECT) -f $(LOCAL_DOCKER_COMPOSE_FILE) restart api aria-worker-main aria-agent-worker aria-agent-beat && \
		$(MAKE) -C ../frontend_mockup down && $(MAKE) -C ../frontend_mockup run && \
		$(MAKE) e2e-seed E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
			E2E_MANAGER_EMAIL=$(E2E_MANAGER_EMAIL) E2E_MANAGER_PASSWORD=$(E2E_MANAGER_PASSWORD) \
			E2E_RELEASE_MANAGER_EMAIL=$(E2E_RELEASE_MANAGER_EMAIL) E2E_RELEASE_MANAGER_PASSWORD=$(E2E_RELEASE_MANAGER_PASSWORD); \
	fi
	@ARIA_E2E_REAL=1 ARIA_E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		E2E_FROM=$(if $(E2E_FROM),$(E2E_FROM),0) \
		E2E_MANAGER_EMAIL=$(E2E_MANAGER_EMAIL) E2E_MANAGER_PASSWORD=$(E2E_MANAGER_PASSWORD) \
		E2E_RELEASE_MANAGER_EMAIL=$(E2E_RELEASE_MANAGER_EMAIL) E2E_RELEASE_MANAGER_PASSWORD=$(E2E_RELEASE_MANAGER_PASSWORD) \
		E2E_FRAUD_ANALYST_EMAIL=$(E2E_FRAUD_ANALYST_EMAIL) E2E_FRAUD_ANALYST_PASSWORD=$(E2E_FRAUD_ANALYST_PASSWORD) \
		npm --prefix ../frontend_mockup run test:e2e:real -- $(if $(E2E_GREP),--grep "$(E2E_GREP)")
	@$(MAKE) e2e-presence E2E_BASE_URL=$(if $(E2E_BASE_URL),$(E2E_BASE_URL),http://localhost) \
		E2E_MANAGER_EMAIL=$(E2E_MANAGER_EMAIL) E2E_MANAGER_PASSWORD=$(E2E_MANAGER_PASSWORD)

.PHONY: sample-docs
sample-docs:  ## Wipe lupita-documents/ and copy N random files from lupita-documents$(SRC)/. Vars: SRC(2) N(10) MINSIZE(0, bytes) ORDER(random|name|size)
	@set -uo pipefail; \
	SRC_SUFFIX="$${SRC:-2}"; \
	SRC_DIR="lupita-documents$$SRC_SUFFIX"; \
	DEST_DIR="lupita-documents"; \
	N="$${N:-10}"; \
	MINSIZE="$${MINSIZE:-0}"; \
	ORDER="$${ORDER:-random}"; \
	if [ ! -d "$$SRC_DIR" ]; then echo "Source $$SRC_DIR not found"; exit 1; fi; \
	echo "Wiping $$DEST_DIR/ ..."; \
	mkdir -p "$$DEST_DIR"; \
	find "$$DEST_DIR" -mindepth 1 -delete; \
	echo "Sampling $$N files from $$SRC_DIR (minsize=$$MINSIZE bytes, order=$$ORDER) ..."; \
	TMP_LIST=$$(mktemp); \
	trap 'rm -f "$$TMP_LIST"' EXIT; \
	find "$$SRC_DIR" -type f -size +$${MINSIZE}c > "$$TMP_LIST"; \
	TOTAL=$$(wc -l < "$$TMP_LIST" | tr -d ' '); \
	if [ "$$TOTAL" -eq 0 ]; then echo "No files match minsize=$$MINSIZE in $$SRC_DIR"; exit 1; fi; \
	echo "Candidates: $$TOTAL"; \
	case "$$ORDER" in \
	  random) sort -R "$$TMP_LIST" | head -n "$$N" > "$$TMP_LIST.picked";; \
	  name)   sort    "$$TMP_LIST" | head -n "$$N" > "$$TMP_LIST.picked";; \
  size)   while IFS= read -r f; do sz=$(stat -fmt '%s' $${f} 2>/dev/null); [ -n "$$sz" ] && printf '%s\t%s\n' "$$sz" "$$f"; done < "$$TMP_LIST" | sort -rn | head -n "$$N" | cut -f2- > "$$TMP_LIST.picked";;	  *) echo "Unknown ORDER=$$ORDER (use: random|name|size)"; exit 1;; \
	esac; \
	while IFS= read -r f; do \
	  [ -z "$$f" ] && continue; \
	  cp "$$f" "$$DEST_DIR/"; \
	  echo "  + $$(basename "$$f")"; \
	done < "$$TMP_LIST.picked"; \
	rm -f "$$TMP_LIST.picked"; \
	COPIED=$$(find "$$DEST_DIR" -maxdepth 1 -type f | wc -l | tr -d ' '); \
	echo "Done. $$COPIED file(s) in $$DEST_DIR/"

.PHONY: configure-artifactory
configure-artifactory:  # Configure artifactory
	@echo "Configuring artifactory"
	@poetry config http-basic.BBVARepo $(ARTIFACTORY_USER) $(ARTIFACTORY_PASSWORD)

.PHONY: build
build: download-poetry configure-artifactory install  ## Build the project.

.PHONY:
run-isort:  ## Run isort to organize imports.
	@echo "Running isort to organize imports... 🪄"
	@poetry run isort .

.PHONY:
run-black:  ## Run black to format code.
	@echo "Running black to format code... 🪄"
	@poetry run black .

.PHONY:
run-flake8:  ## Run flake8 to revision code format.
	@echo "Running flake8 to revision code format... 🪄"
	@poetry run flake8 --config pyproject.toml

.PHONY:
run-pautoflake:  ## Run pautoflake to delete unused imports.
	@echo "Running pautoflake to delete unused imports... 🪄"
	@poetry run pautoflake --config pyproject.toml ./src ./tests

# Stress tests run on the HOST machine (outside any container) and hit the API
# over the network. locust has no project imports so it needs only its own package.
# Install once with: pip install -r tests/stress/requirements.txt
# The API must be reachable at HOST (default: Docker-exposed http://localhost:8000).

.PHONY: stress-install
stress-install:  ## Install locust for stress testing (no project venv required).
	@pip install -r tests/stress/requirements.txt

.PHONY: stress-test
stress-test:  ## Stress test — web UI at http://localhost:8089. Override: make stress-test HOST=http://host:8000
	@locust -f tests/stress/locustfile.py --host $(or $(HOST),http://localhost:8000)

.PHONY: stress-test-headless
stress-test-headless:  ## Headless stress test. Vars: HOST, USERS(10), RATE(2), TIME(3m), SHAPE(spike|ramp|soak)
	@mkdir -p results
	@STRESS_SHAPE=$(or $(SHAPE),) \
	locust -f tests/stress/locustfile.py \
		--host $(or $(HOST),http://localhost:8000) \
		--headless \
		-u $(or $(USERS),10) \
		-r $(or $(RATE),2) \
		--run-time $(or $(TIME),3m) \
		--csv results/stress_$(shell date +%Y%m%d_%H%M%S) \
		--html results/stress_$(shell date +%Y%m%d_%H%M%S).html

# ---------------------------------------------------------------------------
# Agent stress test — parameterised by use case, user count and request delay.
#
# Usage:
#   make stress-test-agent use-case=v1    users=10 delay-between-requests=5
#   make stress-test-agent use-case=multi users=5  delay-between-requests=30
#   make stress-test-agent use-case=both  users=20 delay-between-requests=10
#
# Parameters (all optional, defaults shown):
#   use-case               v1 | multi | both   (default: both)
#   users                  virtual users       (default: 10)
#   delay-between-requests seconds per user    (default: 5)
#   HOST                   API base URL        (default: http://localhost:8000)
#   TIME                   run duration        (default: 5m)
#   RATE                   spawn rate users/s  (default: 2)
#   SHAPE                  spike|ramp|soak     (default: none)
#   STOP_TIMEOUT           seconds to wait for in-flight requests to finish
#                          before shutting down (default: 180 — covers multi max latency)
#
# How it maps to concurrency (4 workers × semaphore=5):
#   v1   (4–60 s):   users=10, delay=5  → ~8 in-flight, well within 20-slot ceiling
#   multi (30–120 s): users=5,  delay=30 → ~4 in-flight, safe
#   both  mixed:      users=20, delay=10 → approaching the 20-slot ceiling
# ---------------------------------------------------------------------------

# Resolve use-case at make-time so _TAGS is available in the recipe.
_UC    := $(or $(use-case),both)
_TAGS  := $(if $(filter v1,$(_UC)),--tags v1,$(if $(filter multi,$(_UC)),--tags multi,--tags agent))

.PHONY: stress-test-agent
stress-test-agent:  ## Agent stress test: use-case=v1|multi|both users=N delay-between-requests=N HOST=... TIME=5m
	@mkdir -p results
	@STRESS_USE_CASE=$(_UC) \
	STRESS_DELAY=$(or $(delay-between-requests),5) \
	STRESS_SHAPE=$(or $(SHAPE),) \
	locust -f tests/stress/locustfile.py \
		--host $(or $(HOST),http://localhost:8000) \
		-u $(or $(users),10) \
		-r $(or $(RATE),2) \
		--run-time $(or $(TIME),5m) \
		--stop-timeout $(or $(STOP_TIMEOUT),180) \
		$(_TAGS) \
		--csv results/stress_agent_$(_UC)_$(shell date +%Y%m%d_%H%M%S) \
		--html results/stress_agent_$(_UC)_$(shell date +%Y%m%d_%H%M%S).html

.PHONY: help
help:  ## Show this help.
	@echo "Use: make <target>"
	@echo ""
	@echo "Targets available:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
.PHONY: run-ruff
run-ruff: run-ruff-lint run-ruff-format  ## Run ruff to delete unused imports.

.PHONY: run-ruff-lint
run-ruff-lint:  ## Run ruff lint to delete unused imports.
	@echo "Running ruff lint to delete unused imports... 🪄"
	@poetry run ruff check --fix .

.PHONY: run-ruff-format
run-ruff-format:  ## Run ruff format to delete unused imports.
	@echo "Running ruff format to delete unused imports... 🪄"
	@poetry run ruff format .

# Static checks. `lint` is what CI runs: ruff + mypy against the committed
# baseline in .lint-baseline.json (fails only when the error count GROWS), so it
# can gate merges while the existing backlog is paid down. Config lives in
# ruff.toml / mypy.ini. After a cleanup, lower the baseline with `make lint-baseline`.
.PHONY: lint
lint:  ## Ratcheted ruff + mypy (CI gate): fail if errors exceed .lint-baseline.json.
	@python scripts/lint_ratchet.py ruff mypy

.PHONY: lint-baseline
lint-baseline:  ## Rewrite .lint-baseline.json with the current ruff/mypy error counts.
	@python scripts/lint_ratchet.py ruff mypy --update

.PHONY: lint-strict
lint-strict:  ## Zero-tolerance ruff check + format check (no baseline). Use once the backlog is fixed.
	@ruff check src tests scripts
	@ruff format --check src tests scripts

.PHONY: typecheck
typecheck:  ## Run mypy (src/domain + src/application, see mypy.ini) and list every error.
	@mypy --config-file mypy.ini

# Static dead-code scan. It never modifies source files. The default confidence
# (80%) focuses on unreachable code and unused imports; use 60 for a broader
# review that will include framework-driven functions and therefore needs
# manual triage.
DEAD_CODE_CONFIG ?= deploy/requirements/pyproject.toml
DEAD_CODE_MIN_CONFIDENCE ?= 80

.PHONY: dead-code
dead-code:  ## Report statically-detectable dead code (override DEAD_CODE_MIN_CONFIDENCE=60 for review).
	@echo "Running Vulture (minimum confidence: $(DEAD_CODE_MIN_CONFIDENCE)%)..."
	@poetry run vulture --config $(DEAD_CODE_CONFIG) --min-confidence $(DEAD_CODE_MIN_CONFIDENCE)


.PHONY: update-poetry-internally
update-poetry-internally:  ## Update poetry internally.
	@lupi_docs_dir="$(shell pwd)/lupita-documents"; \
	    echo "Updating poetry internally... 🪄"; \
	    if [ ! -d "$$lupi_docs_dir" ]; then \
	        echo "Error: $$lupi_docs_dir folder does not exist."; \
	        exit 1; \
	    fi; \
	    if [ -f "$$lupi_docs_dir/pyproject.toml" ]; then \
	        echo "Removing $$lupi_docs_dir/pyproject.toml..."; \
	        rm "$$lupi_docs_dir/pyproject.toml"; \
	    fi; \
	    echo "checking envar "; \
	    echo "ARTIFACTORY_USER: $(ARTIFACTORY_USER)"; \
	    echo "ARTIFACTORY_PASSWORD: $(ARTIFACTORY_PASSWORD)"; \
	    cp ./pyproject.toml "$$lupi_docs_dir/pyproject.toml";
	docker compose -f deploy/docker-compose.standalone.yml -p lupita-data exec api bash -c '\
	    if ! command -v pip >/dev/null 2>&1; then \
	        echo "pip not found, installing pip..."; \
	        apt-get update && apt-get install -y --no-install-recommends python3-pip; \
	    fi; \
	    if python3 -m pip show poetry >/dev/null 2>&1; then \
	        echo "Poetry is already installed as a Python package."; \
	    elif command -v poetry >/dev/null 2>&1; then \
	        echo "Poetry is already installed as a Linux package."; \
	    else \
	        echo "Poetry is not installed. Installing poetry..."; \
	        python3 -m pip install --no-cache-dir poetry==$(POETRY_VERSION); \
	    fi'
	docker compose -f deploy/docker-compose.standalone.yml -p lupita-data exec api bash -c "rm -f ./lupita-documents/poetry.lock && \
	cp ./lupita-documents/pyproject.toml ./ && \
	poetry config http-basic.BBVARepo $(ARTIFACTORY_USER) $(ARTIFACTORY_PASSWORD) && \
	poetry lock && \
	cp ./poetry.lock ./lupita-documents/ && \
	echo 'poetry.lock updated'"
	cp ./lupita-documents/poetry.lock ./
