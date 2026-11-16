# Portfolio platform: unified entrypoint bridging the two native toolchains
# (pnpm + uv) and Docker Compose. Zero extra install on the Oracle box.
#
# Native dev (fast local loop):  make install -> make dev-web / dev-cp / dev-agent
# Deploy (the VM):               make render prepare up   (make down to stop)
.DEFAULT_GOAL := help

# .env is optional; plain KEY=value lines (see .env.example). Values given on the
# command line (make up ORCH_INCLUDE_HIDDEN=1) win over .env.
-include .env

ORCH_PROJECTS_DIR ?= $(CURDIR)/projects
ORCH_REPOS_DIR ?= $(CURDIR)/.dev/repos
export ORCH_PROJECTS_DIR ORCH_REPOS_DIR ORCH_INCLUDE_HIDDEN HTTP_PORT

.PHONY: help install lint dev-web dev-cp dev-agent test build render prepare up down logs e2e clean

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
	ORCH_PROJECTS_DIR=$(ORCH_PROJECTS_DIR) \
	ORCH_INCLUDE_HIDDEN=1 \
	ORCH_COOKIE_SECURE=false \
	uv run --package control-plane python -m control_plane.main

dev-agent: ## Run the agent (reconciler against the local control-plane)
	mkdir -p $(ORCH_REPOS_DIR)
	ORCH_CONTROL_PLANE_URL=http://localhost:8001 \
	ORCH_PROJECTS_DIR=$(ORCH_PROJECTS_DIR) \
	ORCH_REPOS_DIR=$(ORCH_REPOS_DIR) \
	ORCH_INCLUDE_HIDDEN=1 \
	uv run --package agent python -m agent

lint: ## Run every pre-commit hook against the whole repo
	uv run --frozen pre-commit run --all-files

test: ## Run the Python test suites
	uv run --package control-plane pytest services/control-plane
	uv run --package agent pytest services/agent

build: ## Build all platform images (docker compose)
	docker compose build

render: ## Write infra/proxy/generated/projects.conf from the manifests
	uv run --frozen orchctl render-nginx --out infra/proxy/generated/projects.conf

prepare: ## Clone project repos and build/pull their images (never at visitor time)
	mkdir -p $(ORCH_REPOS_DIR)
	uv run --frozen orchctl prepare

up: ## Start the platform (creates the orch-stacks network, then compose up)
	mkdir -p $(ORCH_REPOS_DIR)
	docker network inspect orch-stacks >/dev/null 2>&1 || docker network create orch-stacks
	docker compose up -d --build

down: ## Stop the platform and any running project stacks
	-for p in $$(docker compose ls --all --format json | python3 -c 'import json,sys; print(" ".join(x["Name"] for x in json.load(sys.stdin) if x["Name"].startswith("orch-")))'); do docker compose -p $$p down --remove-orphans; done
	docker compose down

logs: ## Tail platform logs
	docker compose logs -f

e2e: ## End-to-end test: brings the real stack up with the example projects
	uv run --frozen pytest -m integration tests/integration -v

clean: ## Remove build artifacts and virtualenvs (keeps lockfiles)
	rm -rf .venv apps/lab/dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
