# 0002 — Dual native workspaces (pnpm + uv), no meta-orchestrator

- **Status:** Accepted
- **Date:** 2026-07-23
- **Deciders:** Owner + WS-P0.1
- **Decision ref:** D2

## Context

The platform repo holds both JS/TS packages (a landing app + shared packages) and
Python services (control-plane + agent). We need a monorepo strategy that keeps
both toolchains first-class without heavyweight glue.

## Options considered

- **A. Dual native workspaces (chosen).** A pnpm workspace (`apps/*`, `packages/*`)
  and a uv workspace (`services/*`) side by side at the repo root, unified by a
  root `Makefile`.
- **B. JS meta-orchestrator (Turborepo / Nx).** Task graph + caching across
  packages. Rejected: heavy tool + config, JS-centric (awkward for the Python
  services), premature at scaffold time.
- **C. Polyrepo (split JS and Python within the platform).** Rejected: loses
  atomic commits across shared platform contracts (notify-client, health schemas),
  multiplies infra. (Distinct from the *app-repo* split in
  [0005](0005-platform-repo-boundary.md), where the ML apps genuinely ship
  independently.)

## Decision

Adopt **Approach A** — two native workspaces in one repo, glued by a root
`Makefile`, with Docker Compose layered on top for reproducible VM deploy.

## Consequences

- Each toolchain is used exactly as designed; near-zero extra config.
- **Trade-off:** two lockfiles (`pnpm-lock.yaml`, `uv.lock`) and two install steps,
  mitigated by `make install` running both.
- Best fit for a solo maintainer; revisit B only if cross-package build caching
  becomes a real bottleneck.
