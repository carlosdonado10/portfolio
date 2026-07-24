# Portfolio Platform

The **platform** repo for the portfolio system: the landing page, the control
tier (a web API + a privileged host agent), and auth wiring. It is a monorepo
that binds two native toolchains — **pnpm** (frontend + shared JS packages) and
**uv** (Python services) — with a **Docker Compose** path for reproducible
deployment on the Oracle Cloud ARM box.

## Repo boundary (read this first)

This repo is **only** the platform:

- **Landing page** — `apps/landing` (Vite + React + TypeScript).
- **Control tier** — `services/control-plane` (web API) and `services/agent`
  (privileged host agent). The agent is the trusted half of the control tier and
  lives here.
- **Auth** — an explicit pillar, wired at this stage as **Supabase connection env
  only** (`.env.example`). Auth schema/logic is WS0.3; forward-auth proxy is WS0.2.

**Each portfolio/ML application lives in its own separate repo.** The agent
clones/pulls those repos and runs *their* compose one-at-a-time via the Docker
socket at runtime. They are **not** vendored here, **not** submodules, and **not**
in this repo's `docker-compose.yml`. See
[`docs/decisions/0005`](docs/decisions/0005-platform-repo-boundary.md).

## Layout

```text
portfolio/
├── apps/
│   └── landing/           # Vite react-ts landing app (@portfolio/landing)
├── packages/
│   ├── design-system/     # PLACEHOLDER — @portfolio/design-system (WS-DS.0)
│   └── notify-client/     # PLACEHOLDER — @portfolio/notify-client (WS5.4)
├── services/
│   ├── control-plane/     # uv member — FastAPI web API (GET /health)
│   └── agent/             # uv member — privileged host agent (heartbeat)
├── infra/proxy/           # PLACEHOLDER — reverse proxy + forward-auth (WS0.2)
├── supabase/              # PLACEHOLDER — managed, off-box auth + state (WS0.3)
├── docs/decisions/        # ADRs (0001–0005)
├── docker-compose.yml     # 3 platform services; only agent gets the Docker socket
├── Makefile               # unified install / dev / build / up / down
├── pnpm-workspace.yaml    # pnpm workspace: apps/*, packages/*
└── pyproject.toml         # uv virtual workspace: services/*
```

## Version pins

| Tool   | Version | Pinned by |
| ------ | ------- | --------- |
| Node   | 24 (LTS) | `.nvmrc`, `engines.node` in `package.json`, `packageManager` (Corepack) |
| pnpm   | 11.17.0 | `packageManager` in `package.json` (Corepack) |
| Python | 3.13    | `.python-version`, `requires-python` in each service `pyproject.toml` |
| uv     | 0.11.8  | pinned in the service `Dockerfile`s |

`uv` provisions CPython 3.13 into `.venv` regardless of the host's system Python.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) ≥ 0.11
- Node 24 (`nvm use` reads `.nvmrc`) with Corepack enabled (`corepack enable`)
- Docker + Compose v2 (only for the containerized deploy path)

## Native development (fast local loop)

```bash
make install      # pnpm install + uv sync
make dev-web      # landing app        → http://localhost:5173
make dev-cp       # control-plane API  → http://localhost:8000  (GET /health)
make dev-agent    # agent heartbeat loop
make test         # Python test suites
```

Equivalent raw commands (no Make):

```bash
pnpm install && uv sync
pnpm --filter @portfolio/landing dev
uv run --package control-plane uvicorn control_plane.app:app --reload
uv run --package agent python -m agent
```

## Containerized deploy (reproducible, the Oracle VM)

```bash
cp .env.example .env    # fill in Supabase values; .env is gitignored
make build              # docker compose build   (landing, control-plane, agent)
make up                 # docker compose up -d
make down
```

Default ports: landing `:8080`, control-plane `:8000` (override via `.env`).

### Target architecture — `linux/arm64` (Oracle Ampere A1)

All base images are multi-arch (`node:24-slim`, `python:3.13-slim`,
`nginx:alpine`). Build **on the box**, or cross-build from an x86 machine:

```bash
docker buildx build --platform linux/arm64 -f services/control-plane/Dockerfile .
```

### Socket isolation (structural security boundary)

Only the **agent** service bind-mounts `/var/run/docker.sock`. The web-facing
`landing` and `control-plane` have **no route to the socket in the compose file**
— the isolation is topology, not policy. Verify:

```bash
docker compose config | grep -c docker.sock   # → 2 (source+target, agent only)
```

See [`docs/decisions/0004`](docs/decisions/0004-docker-compose-topology-and-socket-isolation.md).

## Decisions

Architecture decisions are recorded as ADRs in
[`docs/decisions/`](docs/decisions/):

- [0001 — Vite over Create React App](docs/decisions/0001-vite-over-cra.md)
- [0002 — Dual native workspaces (pnpm + uv)](docs/decisions/0002-dual-uv-pnpm-workspaces.md)
- [0003 — Node & Python version pins](docs/decisions/0003-node-and-python-version-pins.md)
- [0004 — Docker Compose topology & socket isolation](docs/decisions/0004-docker-compose-topology-and-socket-isolation.md)
- [0005 — Platform repo boundary](docs/decisions/0005-platform-repo-boundary.md)

## Changelog

Notable changes are tracked in [`CHANGELOG.md`](CHANGELOG.md).
