.DEFAULT_GOAL := help
SHELL := /bin/bash
PY := backend/.venv/bin
COMPOSE ?= docker compose

.PHONY: validate-config help install dev build up down logs test test-backend test-frontend test-e2e lint format typecheck migrate seed backup restore clean

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n",$$1,$$2}'

install: ## Install backend (venv) and frontend dependencies
	python3 -m venv backend/.venv
	$(PY)/pip install -q -e "backend[dev]"
	cd frontend && npm ci

dev: ## Run backend (:8000) and frontend (:5173) in dev mode (needs IGUARD_DATABASE_URL or SQLite default)
	@echo "Backend: http://localhost:8000/docs   Frontend: http://localhost:5173"
	cd backend && ../$(PY)/alembic upgrade head
	( cd backend && ../$(PY)/uvicorn app.main:app --reload --port 8000 ) & ( cd frontend && npm run dev ) ; wait

build: ## Build frontend bundle and container images
	cd frontend && npm run build
	$(COMPOSE) build

up: ## Start the full stack (requires .env; run scripts/install.sh first)
	$(COMPOSE) up -d --build

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow stack logs
	$(COMPOSE) logs -f --tail=100

test: test-backend test-frontend ## Run backend and frontend unit/API tests

test-backend: ## Pytest (SQLite; set IGUARD_TEST_DATABASE_URL to use PostgreSQL)
	cd backend && ../$(PY)/python -m pytest tests -p no:cacheprovider

test-frontend: ## Vitest
	cd frontend && npm test

test-e2e: ## Playwright (needs a running stack; see docs/TESTING.md)
	cd frontend && npx playwright test

lint: ## ruff, mypy, eslint, tsc
	cd backend && ../$(PY)/ruff check . && ../$(PY)/ruff format --check . && ../$(PY)/mypy app
	cd frontend && npm run lint && npx tsc --noEmit

format: ## Auto-format backend code
	cd backend && ../$(PY)/ruff check --fix . ; ../$(PY)/ruff format .

validate-config: ## Validate .env, compose files and recovery policies
	scripts/validate-config.sh

migrate: ## Apply database migrations in the running backend container
	$(COMPOSE) exec backend alembic upgrade head

seed: ## Create demo users/services (development only)
	$(COMPOSE) exec backend python -m app.cli seed

backup: ## Backup PostgreSQL to ./backups
	scripts/backup.sh

restore: ## Restore: make restore FILE=backups/iguard-....sql.gz
	scripts/restore.sh $(FILE)

clean: ## Remove build artifacts and caches (does not touch Docker volumes)
	rm -rf frontend/dist frontend/coverage frontend/test-results frontend/playwright-report
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf backend/.mypy_cache backend/.ruff_cache backend/.pytest_cache backend/htmlcov backend/.coverage
