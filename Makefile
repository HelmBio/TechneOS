# TechneOS

.PHONY: help up down down-v logs ps migrate migrate-new migrate-down install lint format typecheck clean

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

# --- Database ---

migrate: ## Run Alembic migrations
	uv run alembic upgrade head

migrate-new: ## Create new migration (usage: make migrate-new msg="add users table")
	uv run alembic revision --autogenerate -m "$(msg)"

migrate-down: ## Rollback last migration
	uv run alembic downgrade -1

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

# --- Cleanup ---

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
