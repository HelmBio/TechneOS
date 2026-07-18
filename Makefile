# TechneOS

.PHONY: help up down down-v logs ps sync-idp-secrets migrate migrate-new migrate-down seed publish-wheels register-platform-assistant install lint format typecheck test test-unit test-integration test-cov test-cli test-management test-tool-runtime test-execution test-all dev-gateway dev-auth dev-dataset dev-tool dev-pipeline dev-agent dev-notification dev-app dev-task dev-cli dev-all dev-all-portal dev-stop dev-portal install-portal build-portal test-portal clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Docker Compose ---

up: ## Start all services
	docker compose up -d

down: ## Stop all services
	docker compose down

down-v: ## Stop all services and remove volumes
	docker compose down -v

logs: ## Tail logs for all services
	docker compose logs -f

ps: ## Show running services
	docker compose ps

# --- Keycloak ---

sync-idp-secrets: ## Re-sync Google/GitHub OAuth credentials into the running Keycloak realm from .env
	./bin/sync-keycloak-idp-secrets.sh

# --- Database ---

migrate: ## Run Alembic migrations
	uv run alembic upgrade head

migrate-new: ## Create new migration (usage: make migrate-new msg="add users table")
	uv run alembic revision --autogenerate -m "$(msg)"

migrate-down: ## Rollback last migration
	uv run alembic downgrade -1

backup: ## Dump every database + the object store to ./backups/<timestamp>/
	./bin/data-admin.sh backup --env local

reset-data: ## DESTRUCTIVE — empty every database, bucket and cache (prompts first)
	./bin/data-admin.sh reset --env local

restore: ## Restore from a backup (usage: make restore dir=./backups/<timestamp>)
	./bin/data-admin.sh restore --env local --dir $(dir)

# --- Platform setup (run once after infra is up, before catalog registration) ---
# See setup/ for the full sequence a platform admin runs on a fresh deployment.

seed: ## Seed default roles, org, team, admin user, and LLM provider (run after migrate)
	uv run python migrations/seed/seed.py

publish-wheels: ## Build + publish the platform wheels the catalog imports (tool-runtime, management)
	./bin/build-register-platform-wheels.sh

register-platform-assistant: ## Register the built-in Platform Assistant against the seeded LLM provider (needs the stack up)
	uv run python setup/register_platform_assistant.py

# --- Development ---

install: ## Install all workspace dependencies
	uv sync --all-packages

lint: ## Run linter
	uv run ruff check .

format: ## Format code
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Run type checker
	uv run mypy packages/

# --- Testing ---
# The top-level tests/ suite covers the server-side integrated platform (core,
# gateway, the eight services). Packages shipped or run OUTSIDE the platform
# deployment own their tests in-package and get a dedicated target: the client
# wheels cli & management, the tool-runtime base wheel, the execution/Airflow
# runtime, and the portal (Vitest). `make test-all` runs everything.

test: ## Run the integrated-platform tests (top-level tests/, excludes integration)
	uv run pytest -v

test-unit: ## Run the integrated-platform unit tests only
	uv run pytest tests/unit -v

test-integration: ## Run integration tests only (requires the stack up: make up)
	uv run pytest -m integration -v

test-cov: ## Run the integrated-platform tests with coverage
	uv run pytest --cov=packages --cov-report=term-missing

test-cli: ## Run the CLI client's in-package tests
	uv run pytest packages/cli/tests -v

test-management: ## Run the management client's in-package tests
	uv run pytest packages/management/tests -v

test-tool-runtime: ## Run tool-runtime's in-package tests
	uv run pytest packages/tool-runtime/tests -v

test-execution: ## Run the execution layer's in-package tests (Airflow, out-of-workspace)
	PYTHONPATH=packages/execution uv run pytest packages/execution/tests -v

test-all: ## Run every test suite incl. integration + web portal (requires: make up)
	# Each in-package suite runs in its own pytest process: they each ship a
	# tests/ package, so collecting more than one in a single invocation would
	# collide on the shared `tests` module name.
	uv run pytest -v
	uv run pytest -m integration -v
	uv run pytest packages/cli/tests -v
	uv run pytest packages/management/tests -v
	uv run pytest packages/tool-runtime/tests -v
	PYTHONPATH=packages/execution uv run pytest packages/execution/tests -v
	cd packages/portal && npx vitest run

# --- Services ---

dev-all: ## Start all backend services (use dev-all-portal to include the web portal)
	./bin/dev.sh

dev-all-portal: ## Start all services including the Next.js web portal
	./bin/dev.sh --portal

dev-stop: ## Stop all services started by dev-all
	./bin/dev.sh --stop

dev-gateway: ## Run API gateway in dev mode
	uv run --package gateway uvicorn gateway.main:app --reload --host 0.0.0.0 --port 8000

dev-auth: ## Run auth service in dev mode
	uv run --package auth-service uvicorn auth_service.main:app --reload --port 8001

dev-dataset: ## Run dataset service in dev mode
	uv run --package dataset-service uvicorn dataset_service.main:app --reload --port 8002

dev-tool: ## Run tool registry service in dev mode
	uv run --package tool-service uvicorn tool_service.main:app --reload --port 8003

dev-pipeline: ## Run pipeline service in dev mode
	uv run --package pipeline-service uvicorn pipeline_service.main:app --reload --port 8004

dev-agent: ## Run agent service in dev mode
	uv run --package agent-service uvicorn agent_service.main:app --reload --port 8005

dev-notification: ## Run notification service in dev mode
	uv run --package notification-service uvicorn notification_service.main:app --reload --port 8006

dev-app: ## Run app service in dev mode
	uv run --package app-service uvicorn app_service.main:app --reload --port 8007

dev-task: ## Run task service in dev mode
	uv run --package task-service uvicorn task_service.main:app --reload --port 8008

# --- CLI ---

dev-cli: ## Run the CLI (usage: make dev-cli cmd="dataset list")
	uv run python -m techneos_cli.main $(cmd)

build-cli-wheel: ## Build the techneos-cli wheel the gateway serves at /cli/simple/
	bin/build-cli-wheel.sh

# --- Web portal ---

dev-portal: ## Run Next.js web portal in dev mode (port 3000)
	bash bin/generate-portal-env.sh .env
	cd packages/portal && npx next dev --webpack --hostname 0.0.0.0

install-portal: ## Install web portal dependencies
	cd packages/portal && npm install
	bash bin/generate-portal-env.sh .env

build-portal: ## Build web portal for production
	bash bin/generate-portal-env.sh .env
	cd packages/portal && npx next build --webpack

test-portal: ## Run Next.js frontend tests
	cd packages/portal && npx vitest run

# --- Cleanup ---

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
