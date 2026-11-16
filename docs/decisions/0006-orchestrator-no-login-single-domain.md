# 0006 — Orchestrator: no login, single domain, manifest registry

- **Status:** Accepted
- **Date:** 2026-11-15
- **Deciders:** Owner
- **Spec:** [`docs/superpowers/specs/2026-11-15-orchestrator-design.md`](../superpowers/specs/2026-11-15-orchestrator-design.md)
- **Supersedes:** the auth item of [ADR 0005](0005-platform-repo-boundary.md)

## Context

The platform became a project-agnostic orchestrator: it runs one project's
docker-compose stack at a time on a 2-vCPU box, with a lease and a queue when
visitors contend. ADR 0005 planned managed auth (Supabase) with a forward-auth
proxy. For a public portfolio demo that gate costs more than it protects, and it
adds an off-box dependency.

## Decision

1. **No login.** A visitor gets an anonymous signed cookie that identifies them
   for the lease and the queue. An email address is optional, used only to notify
   them when their turn comes up.
2. **One domain, path routing through nginx.** `/p/<id>/` routes to the running
   project's stack and `/lab/` serves the lab front end. `orchctl render-nginx`
   renders the routing config from the manifests at deploy time; nothing is
   exposed on per-project ports or subdomains.
3. **Project registry of manifests.** Each project is described by a manifest in
   `projects/`. The project's code stays in its own repo, cloned by
   `orchctl prepare`, consistent with ADR 0005: nothing is vendored here, and no
   project is a submodule.
4. **Supabase is dropped.** There is no managed auth or state store. Lease and
   queue state live on the box.

## Consequences

- No account system, session store or forward-auth proxy to build or secure.
- Abuse control rests on the lease and queue (one stack at a time, time-boxed),
  not on identity.
- Adding a project means adding a manifest, not changing platform code.
- **Same-origin trust assumption.** Projects run on the lab's origin, so their
  JavaScript is same-origin with `/api/`. Mitigations: nginx strips every `orch_*`
  cookie before proxying to a project upstream, the admin cookie is scoped to
  `Path=/api/admin`, and every cookie is httpOnly. What remains: a project page
  can still call `/api/*` with the visitor's own cookie (it is that visitor's
  session anyway), and while the owner is signed in, a project page could call
  the admin API with the browser's admin cookie. So the owner should sign out
  of `/lab/admin` before browsing projects; the admin console can move to its own
  origin later if that becomes a real risk.
- The Supabase env wiring, the `supabase/` placeholder and the design-system
  placeholder are removed. A design-system package is recreated when its
  workstream starts.
