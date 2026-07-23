# 0005 — Platform repo boundary (this repo vs the app repos)

- **Status:** Accepted
- **Date:** 2026-07-23
- **Deciders:** Owner + WS-P0.1
- **Decision ref:** D9

## Context

The portfolio system is a control platform that hosts several ML/portfolio
applications on one box. A boundary question: does this repo also contain those
applications, or only the platform that runs them?

## Decision

**This repo is the platform, and only the platform:**

1. **Landing page** — `apps/landing`.
2. **Control tier** — `services/control-plane` (web API) **and**
   `services/agent` (privileged host agent). *The agent lives here*, as the
   trusted half of the control tier.
3. **Auth** — an explicit pillar, but at scaffold time satisfied by **Supabase
   connection env wiring only** (`.env.example`). Auth schema/logic is WS0.3;
   forward-auth proxy is WS0.2.

**Each ML/portfolio application lives in its own separate repo.** The agent
clones/pulls those repos and runs *their* compose one-at-a-time via the Docker
socket. They are **not** vendored here, **not** git submodules, and **not** in
this repo's `docker-compose.yml`.

## Rationale

- **Independent deployability.** The platform ships on its own cadence; each app
  repo versions and releases independently.
- **Small, focused monorepo.** Keeping the apps out keeps this tree to the three
  platform concerns above.
- **Clean runtime seam.** The agent's job is to manage *external* app repos at
  runtime; that boundary is clearer when they are physically separate.

## Consequences

- `services/agent` is scaffolded here (stdlib-only stub now; Docker SDK + app-repo
  management land in WS3).
- Acceptance for WS-P0.1 includes a negative check: no ML app is scaffolded,
  submoduled, or added to the platform compose.
- If the agent should later move to its own repo or a host `systemd` unit, that is
  a WS3/WS8 call — this scaffold does not preclude it.
