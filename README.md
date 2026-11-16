# Portfolio Platform

The **platform** repo for the portfolio system: the lab front end, the control
tier (a web API + a privileged host agent), and the shared orchestrator package. It is a monorepo
that binds two native toolchains — **pnpm** (frontend + shared JS packages) and
**uv** (Python services) — with a **Docker Compose** path for reproducible
deployment on the Oracle Cloud ARM box.

## Repo boundary (read this first)

This repo is **only** the platform:

- **Lab app** — `apps/lab` (Vite + React + TypeScript), served at `/lab/`.
- **Control tier** — `services/control-plane` (web API) and `services/agent`
  (privileged host agent). The agent is the trusted half of the control tier and
  lives here.
- **Shared package** — `services/common` (`orch_common`: manifest model, wire
  schemas, `orchctl` CLI).
- **No login** — visitors get an anonymous signed cookie
  ([ADR 0006](docs/decisions/0006-orchestrator-no-login-single-domain.md)).

**Each portfolio/ML application lives in its own separate repo.** The agent
clones/pulls those repos and runs *their* compose one-at-a-time via the Docker
socket at runtime. They are **not** vendored here, **not** submodules, and **not**
in this repo's `docker-compose.yml`. See
[`docs/decisions/0005`](docs/decisions/0005-platform-repo-boundary.md).

## Layout

```text
portfolio/
├── apps/
│   └── lab/               # Vite react-ts lab app (@portfolio/lab), served at /lab/
├── packages/
│   └── notify-client/     # @portfolio/notify-client: SSE toasts + activity beats, injected into projects
├── services/
│   ├── common/            # uv member: orch_common (manifest model, wire schemas, orchctl)
│   ├── control-plane/     # uv member: FastAPI API, lease/queue engine (agent API :8001)
│   └── agent/             # uv member: privileged host agent (reconciler)
├── .github/               # CI workflow and PR template
├── infra/proxy/           # nginx gateway image, config, snippets, generated routes
├── projects/              # project manifests (stack.toml); _examples/ = fast + slow demos
├── tests/integration/     # end-to-end test against the real compose stack (make e2e)
├── docs/
│   ├── decisions/         # ADRs
│   ├── superpowers/       # design specs and implementation plans
│   └── adding-a-project.md  # onboarding checklist for a new project
├── docker-compose.yml     # proxy + control-plane + agent; only agent gets the Docker socket
├── Makefile               # unified install / dev / render / prepare / up / down / e2e
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
make dev-web      # lab app            → http://localhost:5173
make dev-cp       # control-plane API  → http://localhost:8000  (GET /api/health; agent API :8001)
make dev-agent    # agent reconciler (needs a Docker daemon + the control-plane on :8001)
make test         # Python test suites
```

Equivalent raw commands (no Make):

```bash
pnpm install && uv sync
pnpm --filter @portfolio/lab dev
uv run --package control-plane python -m control_plane.main   # needs ORCH_* env, see Makefile dev-cp
uv run --package agent python -m agent
```

## Quickstart: run the whole platform (Docker)

```bash
cp .env.example .env     # set both secrets; for local http also ORCH_COOKIE_SECURE=false
                         # and ORCH_INCLUDE_HIDDEN=1 to see the example projects
make render prepare up   # routes, project images, then the platform
open http://localhost:8080/lab/
make down
```

- `make render` writes `infra/proxy/generated/projects.conf` from the manifests in
  `ORCH_PROJECTS_DIR` (default `./projects`).
- `make prepare` clones project repos and builds their images. Images are never built at
  visitor time.
- `make up` creates the external `orch-stacks` network if missing, then
  `docker compose up -d --build`. Only the nginx proxy publishes a port (`HTTP_PORT`,
  default 8080).
- `make e2e` brings the stack up with short lease timings and runs the integration tests
  (needs Docker). It is **destructive**: it wipes the `portfolio-platform_orch-data` volume
  and tears down every `orch-*` stack, so it refuses to run unless `ORCH_E2E=1`, which
  `make e2e` sets. Never run it on a box with real state.

To add a project, see [`docs/adding-a-project.md`](docs/adding-a-project.md).

### Deploying behind TLS

The gateway speaks plain http. On the server, put a TLS front proxy on the host (Caddy or
the host's nginx) in front of it, and in `.env`:

- `HTTP_BIND=127.0.0.1` so only the front proxy can reach the gateway's port;
- `ORCH_COOKIE_SECURE=true` (the default), which requires HTTPS: browsers drop `Secure`
  cookies over plain http;
- `ORCH_PUBLIC_BASE_URL=https://your.domain` for links in emails.

Then uncomment the `set_real_ip_from` / `real_ip_header` example in
`infra/proxy/nginx.conf` so rate limits see the visitor's IP rather than the front proxy's.
Details in [`infra/proxy/README.md`](infra/proxy/README.md#tls-and-the-real-client-ip).

### Target architecture — `linux/arm64` (Oracle Ampere A1)

All base images are multi-arch (`node:24-slim`, `python:3.13-slim`,
`nginx:1.27-alpine`). Build **on the box**, or cross-build from an x86 machine:

```bash
docker buildx build --platform linux/arm64 -f services/control-plane/Dockerfile .
```

### Socket isolation (structural security boundary)

Only the **agent** service bind-mounts `/var/run/docker.sock`. The web-facing
`proxy` and `control-plane` have **no route to the socket in the compose file**
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
- [0006 — Orchestrator: no login, single domain, manifest registry](docs/decisions/0006-orchestrator-no-login-single-domain.md)

## Changelog

Notable changes are tracked in [`CHANGELOG.md`](CHANGELOG.md).
