# Load variables from .envs/.make if it exists (use -include to not fail if missing)
-include .envs/.make

SHELL := /usr/bin/env bash

# ─── Python runner: use poetry run when available, plain python otherwise ─────
# This allows db-backup/restore commands to work inside Docker containers where
# the venv is already in PATH but poetry is not installed.
PYTHON := $(if $(shell command -v poetry 2>/dev/null),poetry run python,python)

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

.PHONY: create-local-user
create-local-user:  ## Interactively create a local-auth user; no credential is stored by Make.
	@set -euo pipefail; \
	read -r -p "Nombre: " auth_name; \
	read -r -p "Correo: " auth_email; \
	printf '%s\n' "Roles: manager, channel_manager, release_manager, data_analyst, fraud_analyst, ops_analyst"; \
	read -r -p "Rol: " auth_role; \
	case "$$auth_role" in manager|channel_manager|release_manager|data_analyst|fraud_analyst|ops_analyst) ;; *) echo "Rol no válido." >&2; exit 1;; esac; \
	read -r -s -p "Contraseña: " auth_password; printf '\n'; \
	read -r -s -p "Repite la contraseña: " auth_password_confirm; printf '\n'; \
	[ "$$auth_password" = "$$auth_password_confirm" ] || { echo "Las contraseñas no coinciden." >&2; exit 1; }; \
	read -r -s -p "Token de aprovisionamiento: " auth_bootstrap_token; printf '\n'; \
	read -r -p "URL de API [http://localhost:8000]: " auth_api_url; \
	auth_api_url=$${auth_api_url:-http://localhost:8000}; \
	auth_curl_config=$$(mktemp); trap 'rm -f "$$auth_curl_config"' EXIT; chmod 600 "$$auth_curl_config"; \
	printf 'header = "X-Bootstrap-Token: %s"\n' "$$auth_bootstrap_token" > "$$auth_curl_config"; \
	AUTH_NAME="$$auth_name" AUTH_EMAIL="$$auth_email" AUTH_ROLE="$$auth_role" AUTH_PASSWORD="$$auth_password" \
	python3 -c 'import json, os; print(json.dumps({"name": os.environ["AUTH_NAME"], "email": os.environ["AUTH_EMAIL"], "role": os.environ["AUTH_ROLE"], "password": os.environ["AUTH_PASSWORD"]}))' | \
	curl --fail-with-body --silent --show-error -K "$$auth_curl_config" -H 'Content-Type: application/json' --data-binary @- "$$auth_api_url/api/v0/auth/users"; \
	printf '\nUsuario creado.\n'

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


.PHONY: test-integration-reservations
test-integration-reservations:  ## Run resource-reservation tests (voicebot slots / analyst locks) against the running local DynamoDB. Vars: DYNAMO_PORT(8002)
	GENAI_ENVIRONMENT=test DYNAMO_ENDPOINT=http://localhost:$${DYNAMO_PORT:-8002} DYNAMO_REGION_NAME=us-east-1 \
		DYNAMO_ACCESS_KEY=dummy DYNAMO_SECRET_KEY=dummy \
		python -m pytest -m docker_integration tests/test_integration/test_resource_reservations

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
local-docker-build:  ## Build local Docker API stack. Vars: LOCAL_DOCKER_ENV, LOCAL_API_PORT, LOCAL_DYNAMODB_PORT, LOCAL_IMAGE_TAG
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		build --no-cache

.PHONY: local-docker-run
local-docker-run:  ## Run local Docker API stack + frontend (FRONTEND_DIR, default ../frontend_mockup). LLM/other app config comes from config/$(LOCAL_DOCKER_ENV)/config.cfg, mounted read-only - edit it and re-run this to pick up changes. Vars: LOCAL_DOCKER_ENV, LOCAL_API_PORT, LOCAL_DYNAMODB_PORT, LOCAL_IMAGE_TAG
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		up -d
	@# config.cfg is a mounted file, not a compose-level env var - `up -d`
	@# alone won't notice its content changed, so always restart the two
	@# services that read it. Cheap (no rebuild, no image pull) and a no-op
	@# on freshly-created containers.
	@$(LOCAL_DOCKER_ENV_FLAGS) $(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		restart api worker
	@if [ -d "$(FRONTEND_DIR)" ]; then \
		$(MAKE) -C $(FRONTEND_DIR) run; \
	else \
		echo "FRONTEND_DIR=$(FRONTEND_DIR) not found, skipping frontend."; \
	fi

.PHONY: local-docker-stop
local-docker-stop:  ## Stop local Docker API stack + frontend.
	@$(DOCKER) compose \
		-p $(LOCAL_DOCKER_PROJECT) \
		-f $(LOCAL_DOCKER_COMPOSE_FILE) \
		down
	@if [ -d "$(FRONTEND_DIR)" ]; then \
		$(MAKE) -C $(FRONTEND_DIR) down; \
	else \
		echo "FRONTEND_DIR=$(FRONTEND_DIR) not found, skipping frontend."; \
	fi

# ─── Local observability stack (OTel Collector, Tempo, Loki, Prometheus, Grafana, MinIO) ──
OBSERVABILITY_COMPOSE_FILE ?= deploy/local/docker/observability/docker-compose.observability.yml
OBSERVABILITY_PROJECT ?= aria-observability

.PHONY: observability-up
observability-up:  ## Start the local observability stack (Grafana at :3000).
	@$(DOCKER) compose \
		-p $(OBSERVABILITY_PROJECT) \
		-f $(OBSERVABILITY_COMPOSE_FILE) \
		up -d

.PHONY: observability-down
observability-down:  ## Stop the local observability stack.
	@$(DOCKER) compose \
		-p $(OBSERVABILITY_PROJECT) \
		-f $(OBSERVABILITY_COMPOSE_FILE) \
		down -v

.PHONY: observability-logs
observability-logs:  ## Tail logs for the local observability stack.
	@$(DOCKER) compose \
		-p $(OBSERVABILITY_PROJECT) \
		-f $(OBSERVABILITY_COMPOSE_FILE) \
		logs -f

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
	@$(PYTHON) scripts/db_backup.py backup $(if $(BACKUP_DIR),--dir $(BACKUP_DIR),) $(_OS_FLAG)

.PHONY: db-restore
db-restore:  ## Restore from backup. Vars: BACKUP_DIR(req), SKIP_OBJECT_STORAGE=1, OS_BULK_SIZE=20, OS_CHECKPOINT_FILE=..., RESUME_OPENSEARCH=1
	@if [ -z "$(BACKUP_DIR)" ]; then \
		echo "ERROR: BACKUP_DIR is required. Usage: make db-restore BACKUP_DIR=./backups/<timestamp>"; \
		exit 1; \
	fi
	@$(PYTHON) scripts/db_backup.py restore --dir $(BACKUP_DIR) $(_OS_FLAG) $(_OS_BULK_FLAG) $(_OS_CHECKPOINT_FLAG) $(_OS_RESUME_FLAG)

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
