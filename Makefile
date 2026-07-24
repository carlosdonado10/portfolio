# Portfolio platform — unified entrypoint bridging the two native toolchains
# (pnpm + uv) and Docker Compose. Zero extra install on the Oracle box.
#
# Native dev (fast local loop):  make install → make dev-web / dev-cp / dev-agent
# Reproducible deploy (the VM):  make build   → make up / down
.DEFAULT_GOAL := help

.PHONY: help install dev-web dev-cp dev-agent test build up down logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install both toolchains (pnpm workspace + uv workspace)
	pnpm install
	uv sync

dev-web: ## Run the landing app (Vite dev server)
	pnpm --filter @portfolio/landing dev

dev-cp: ## Run the control-plane API (uvicorn, reload)
	uv run --package control-plane uvicorn control_plane.app:app --reload

dev-agent: ## Run the agent heartbeat loop
	uv run --package agent python -m agent

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
	rm -rf .venv apps/landing/dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
