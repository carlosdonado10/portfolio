# 0004 — Docker Compose topology & Docker-socket isolation

- **Status:** Accepted
- **Date:** 2026-07-23
- **Deciders:** Owner + WS-P0.1
- **Decision refs:** D7, D8

## Context

The platform must deploy reproducibly on the Oracle Cloud free-tier box (Ampere
A1, `linux/arm64`) in one command. The two-tier design has a web-facing API
(control-plane) and a privileged **agent** that brings ML app stacks up/down via
the host Docker daemon. That privilege must not leak to web-facing services.

## Decision

A **root `docker-compose.yml` with three platform services** — `landing`,
`control-plane`, `agent`:

- **`landing`** — `nginx:alpine` serving the built Vite `dist/`.
- **`control-plane`** — FastAPI (uvicorn). **No socket, no host mounts.**
- **`agent`** — the **only** service that bind-mounts `/var/run/docker.sock`;
  `restart: unless-stopped`.

**Target architecture is `linux/arm64`** (D8). All base images are multi-arch
(`python:3.13-slim`, `node:24-slim`, `nginx:alpine`); build on the box or with
`docker buildx --platform linux/arm64`.

### Sub-decision: agent as container with bind-mounted socket

The agent runs as a **container with the socket bind-mounted** (docker-out-of-
docker) rather than a host `systemd` unit, so `docker compose up` is
self-contained. Mounting the socket grants that container root-equivalent access
to the host — which is *exactly why* only the single trusted agent gets it. Final
container-vs-systemd call is deferred to WS3/WS8; the scaffold uses the container
path.

## Rationale

- **Structural isolation.** The web-facing `control-plane` has no route to the
  socket *in the compose file itself* — the boundary is topology, not policy. A
  compromise of the API cannot reach the Docker daemon because the mount does not
  exist for that service.
- **Reproducibility.** One `docker compose up` stands up the whole platform on a
  fresh VM.

## Scope guard

This compose intentionally **excludes**:

- the reverse proxy + forward-auth (Caddy/Traefik + TLS) → **WS0.2**
  (`infra/proxy`); a documented seam is left for it;
- **Supabase** — managed and **off-box**; only its connection env is wired;
- the **five ML apps** — each in its own repo, brought up/down by the agent at
  runtime (see [0005](0005-platform-repo-boundary.md)); each has its own compose.

## Consequences

- Verifiable invariant: `grep docker.sock docker-compose.yml` returns the mount
  under `agent` and nowhere else.
- The landing image builds from the **repo root** context so pnpm can resolve the
  workspace + lockfile.
