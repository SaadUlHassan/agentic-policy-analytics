.DEFAULT_GOAL := help
.PHONY: help up down reset logs ps smoke test test-backend test-frontend lint fmt typecheck probe snapshots

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

up: ## Build and start the full stack, waiting until every service is healthy
	docker compose up -d --build --wait --wait-timeout 180

down: ## Stop the stack (keeps the database volume)
	docker compose down

reset: ## Stop the stack and delete the database volume
	docker compose down -v

logs: ## Follow logs from all services
	docker compose logs -f --tail=100

ps: ## Show service status and health
	docker compose ps

smoke: ## End-to-end check against the running stack (API, DB, Redis, worker job)
	curl -fsS "http://$$(docker compose port api 8000)/api/health" && echo
	docker compose exec -T api python -m app.worker.smoke

test: test-backend test-frontend ## Run all unit tests

test-backend:
	cd backend && uv run pytest --cov --cov-report=term-missing:skip-covered

test-frontend:
	cd frontend && npm test

lint: ## Lint and format-check everything
	cd backend && uv run ruff check . ../scripts && uv run ruff format --check . ../scripts
	cd frontend && npm run lint

fmt: ## Auto-format backend code
	cd backend && uv run ruff check --fix . ../scripts && uv run ruff format . ../scripts

typecheck: ## Static type checks
	cd backend && uv run mypy app
	cd frontend && npm run typecheck

probe: ## LLM capability probe of the configured models (credentials and model IDs from .env)
	cd backend && uv run python ../scripts/probe_llm.py

snapshots: ## Re-capture real-data snapshots from SingStat, Data.gov.sg and MOM
	cd backend && uv run python ../scripts/capture_snapshots.py
