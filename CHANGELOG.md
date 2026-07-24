# Changelog

All notable changes to the portfolio **platform** repo are recorded here. The
format follows [Keep a Changelog](https://keepachangelog.com/); the platform is
pre-release, so entries live under _Unreleased_ until the first tag.

Scope reminder: this repo is the platform only — landing page, control tier
(control-plane + agent), and auth env wiring. The portfolio/ML applications live
in their own repos and are not tracked here (see
[ADR 0005](docs/decisions/0005-platform-repo-boundary.md)).

## [Unreleased]

### Added

- **Two-workspace monorepo.** One `make install` provisions both toolchains — a
  pnpm workspace (`apps/*`, `packages/*`) and a uv workspace (`services/*`) — from
  a single clone.
- **Landing app** (`@portfolio/landing`): a Vite + React + TypeScript site. Run it
  with `make dev-web` (serves on `http://localhost:5173`); production builds to
  static files served by nginx.
- **Control-plane API** (`services/control-plane`): a FastAPI service exposing
  `GET /health → {"status":"ok"}`. Run it with `make dev-cp` (`http://localhost:8000`).
- **Agent** (`services/agent`): the privileged control-tier service, currently a
  heartbeat loop (`make dev-agent`). It is the only component granted the Docker
  socket; ML-app orchestration lands in a later workstream.
- **One-command containerized deploy.** `make build && make up` brings up all three
  services via `docker-compose.yml`, targeting `linux/arm64` (Oracle Ampere).
  Landing is published on `:8080`, control-plane on `:8000` (override in `.env`).
- **Structural socket isolation.** Only the `agent` service mounts
  `/var/run/docker.sock`; the web-facing `landing` and `control-plane` have no
  route to it — the boundary is topology, not policy
  ([ADR 0004](docs/decisions/0004-docker-compose-topology-and-socket-isolation.md)).
- **Auth wiring (env only).** `.env.example` carries the managed, off-box Supabase
  connection values (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`).
  Auth schema and forward-auth are owned by later workstreams.
- **Pinned toolchain versions:** Node 24 (`.nvmrc`, `engines`, Corepack), pnpm
  11.17.0 (`packageManager`), Python 3.13 (`.python-version`, `requires-python`),
  uv 0.11.8 (in the service Dockerfiles).
- **Architecture decision records** `0001`–`0005` under `docs/decisions/`: Vite over
  Create React App, dual uv+pnpm workspaces, the version pins, the Compose topology
  and socket isolation, and the platform repo boundary.
- **Placeholders** for downstream workstreams so the workspaces resolve without
  pulling their scope forward: `@portfolio/design-system` (WS-DS.0),
  `@portfolio/notify-client` (WS5.4), `infra/proxy/` (WS0.2), `supabase/` (WS0.3).
- **Root `Makefile`** bridging both toolchains and Compose: `install`, `dev-web`,
  `dev-cp`, `dev-agent`, `test`, `build`, `up`, `down`, `logs`, `clean`.

### Changed

- **README** rewritten from a one-line stub into full platform documentation: repo
  boundary, layout, version-pin table, native and containerized run commands, and
  the socket-isolation verification.
- **`.gitignore`** extended with Python/uv entries (`.venv/`, `__pycache__/`,
  `*.py[cod]`, tooling caches) alongside the existing Node ignores.
