.DEFAULT_GOAL := help
.PHONY: help up down reset logs ps smoke prod-up prod-down test test-backend test-frontend coverage lint fmt typecheck eval eval-live eval-expected probe snapshots

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

prod-up: ## Production stack from the published images (needs POSTGRES_PASSWORD; faults off)
	docker compose -f docker-compose.prod.yml up -d --wait --wait-timeout 180

prod-down: ## Stop the production stack (keeps its database volume)
	docker compose -f docker-compose.prod.yml down

test: test-backend test-frontend ## Run all unit tests

test-backend:
	cd backend && uv run pytest --cov --cov-report=term-missing:skip-covered

test-frontend:
	cd frontend && npm test

coverage: ## Coverage: backend core packages (gated at 80% in CI) and frontend (reported)
	cd backend && uv run pytest -q --cov --cov-report=xml && uv run coverage report --fail-under=80 --skip-covered \
		--include='app/agents/*,app/analytics/*,app/connectors/*,app/data/*,app/grounding/*,app/jobs/*,app/events/*'
	cd frontend && npm run coverage

lint: ## Lint and format-check everything
	cd backend && uv run ruff check . ../scripts ../eval && uv run ruff format --check . ../scripts ../eval
	cd frontend && npm run lint

fmt: ## Auto-format backend code
	cd backend && uv run ruff check --fix . ../scripts ../eval && uv run ruff format . ../scripts ../eval

typecheck: ## Static type checks
	cd backend && uv run mypy app
	cd frontend && npm run typecheck

eval: ## Deterministic evaluation gates (golden computations, refusals, adversarial suite) -> eval/results
	cd backend && uv run python -m app.evaluation

eval-live: ## Live evaluation on both providers (spends LLM calls; needs Postgres and Redis) -> eval/results/live
	cd backend && uv run python -m app.evaluation.live $(ARGS)

eval-expected: ## Recompute the golden expected values independently from the raw snapshots
	cd backend && uv run python ../eval/compute_expected.py

probe: ## LLM capability probe of the configured models (credentials and model IDs from .env)
	cd backend && uv run python ../scripts/probe_llm.py

snapshots: ## Re-capture real-data snapshots from SingStat, Data.gov.sg and MOM
	cd backend && uv run python ../scripts/capture_snapshots.py
