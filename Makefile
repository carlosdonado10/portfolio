# Portfolio platform — unified entrypoint bridging the two native toolchains
# (pnpm + uv) and Docker Compose. Zero extra install on the Oracle box.
#
# Native dev (fast local loop):  make install → make dev-web / dev-cp / dev-agent
# Reproducible deploy (the VM):  make build   → make up / down
.DEFAULT_GOAL := help

.PHONY: help install lint dev-web dev-cp dev-agent test build up down logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install both toolchains + git hooks (pre-commit, commit-msg)
	pnpm install
	uv sync
	uv run --frozen pre-commit install --install-hooks

dev-web: ## Run the lab app (Vite dev server)
	pnpm --filter @portfolio/lab dev

dev-cp: ## Run the control-plane (public :8000, agent :8001)
	mkdir -p .dev
	ORCH_COOKIE_SECRET=dev-cookie-secret-not-for-prod \
	ORCH_OWNER_SECRET=dev-owner-secret-not-for-prod \
	ORCH_DB_PATH=./.dev/orch.sqlite \
	ORCH_PROJECTS_DIR=./projects \
	ORCH_INCLUDE_HIDDEN=1 \
	ORCH_COOKIE_SECURE=false \
	uv run --package control-plane python -m control_plane.main

dev-agent: ## Run the agent heartbeat loop
	uv run --package agent python -m agent

lint: ## Run every pre-commit hook against the whole repo
	uv run --frozen pre-commit run --all-files

test: ## Run the Python test suites
	uv run --package control-plane pytest services/control-plane
	uv run --package agent pytest services/agent

build: ## Build all platform images (docker compose)
	docker compose build

up: ## Start the platform (docker compose, detached)
	docker compose up -d

down: ## Stop the platform (docker compose)
	docker compose down

logs: ## Tail platform logs
	docker compose logs -f

clean: ## Remove build artifacts and virtualenvs (keeps lockfiles)
	rm -rf .venv apps/lab/dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
