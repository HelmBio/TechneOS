# TechneOS

.PHONY: help up down down-v logs ps sync-idp-secrets migrate migrate-new migrate-down seed install lint format typecheck dev-gateway dev-auth dev-dataset dev-tool dev-pipeline dev-agent dev-notification dev-app dev-task dev-cli dev-all dev-all-portal dev-stop dev-portal install-portal build-portal test-portal clean

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

seed: ## Seed default roles, org, team, and admin user (run after migrate)
	uv run python -m core.database.seed

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

dev-cli: ## Run the CLI (usage: make dev-cli cmd="datasets list")
	uv run python -m cli.main $(cmd)

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
