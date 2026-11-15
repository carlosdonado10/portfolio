# Orchestrator ("the lab") — Design

Date: 2026-11-15
Status: draft for approval

## 1. Intent

Carlos's portfolio contains several runnable ML products (today: rl-control-suite, grid-ml,
rag-pipeline, ml-agent, code-translate — **this list will change**). They all live on one
Oracle Cloud box: **2 vCPU, 24 GB RAM**. CPU makes it impossible to run more than one stack at a time.

The orchestrator lets a visitor (typically an interviewer at an AI lab) pick a project and see it
running live, while guaranteeing only one stack runs at once and handling several visitors fairly.

The orchestrator is **itself one of the showcased portfolio projects**: its UI, its behaviour and
the copy explaining *why* it works this way are part of the portfolio story, not hidden plumbing.

## 2. Goals

- **Project-agnostic.** The orchestrator knows nothing about any particular project. A project plugs in
  by dropping a folder with a manifest + compose file into `projects/`. Adding, swapping or removing a
  project requires no orchestrator code change.
- **One stack at a time**, with a fair, legible handoff between visitors (lease + queue, §6).
- **No login.** Anyone can start or queue a stack. Identity is an anonymous browser session cookie.
  Email is **optional**, used only for "notify me when it's my turn / ready".
- **Single domain**, nginx in front. Projects are served under path prefixes.
- **Security boundary:** nothing web-facing can touch the Docker socket (§5).
- **Ready means serving**, not "compose exited 0" (§7).
- **Copy is a deliverable.** Every status / notification message explains the engineering reason
  (why one at a time, why the socket is isolated, why "started" ≠ "ready").
- Operable and maintainable by one person.

## 3. Non-goals

- Running more than one stack at once, multi-box scheduling, autoscaling.
- User accounts, passwords, OAuth, magic links. (Supabase Auth from the July plan is **dropped**.)
- Building the ML projects themselves, or the personal portfolio landing site (`PortfolioLanding/`).
- A general-purpose PaaS. This only has to serve this box and these visitors.

## 4. Anti-goals (failure even if it "works")

- An interviewer stares at a blank or broken page while a stack boots. There must always be a
  page explaining what's happening, an ETA, and a link to the project's recorded demo.
- Any process reachable from the internet can talk to Docker.
- Adding a project means editing orchestrator code.
- A stuck or crashing stack holds the box forever and blocks the queue.

## 5. Architecture

```
                    internet
                       │
                  ┌────▼─────┐   auth_request /internal/gate/<id>
                  │  nginx   │──────────────────────────┐
                  └┬───┬───┬─┘                          │
       /lab/*      │   │   │  /p/<id>/*                 │
   (orchestrator   │   │   └──────────► active stack    │
       UI, static) │   │                (its compose)   │
                   │   │ /api/*                         │
                   │ ┌─▼────────────────────────┐◄─────┘
                   │ │ control-plane (FastAPI)  │  SQLite (owned solely by control-plane)
                   │ │ lease/queue state machine│
                   │ │ SSE notifications, email │
                   │ └─▲────────────────────────┘
                   │   │ internal-only HTTP (docker network `orch-internal`, no published port)
                   │ ┌─┴────────────────────────┐
                   │ │ agent (reconciler)       │── /var/run/docker.sock
                   │ │ reads projects/*/stack.toml, runs compose up/down, polls health
                   │ └──────────────────────────┘
```

### Components

- **nginx**: the only thing that's internet-facing. It routes:
  - `/lab/` serves the orchestrator UI (static build).
  - `/api/` goes to control-plane (public API + SSE).
  - `/p/<id>/` goes to the project's entry service, **gated** by `auth_request` to control-plane
    `/internal/gate/<id>`. The gate returns 2xx only when that project is the active stack, its
    status is `ready`, **and the request's `orch_sid` is the holder's** (single-user access, §6). Otherwise nginx redirects to the orchestrator's interstitial page
    `/lab/p/<id>` (booting / queued / start, plus ETA and demo link). The gate result may be cached
    for ~1–2s.
  - `/` is left free for the personal portfolio site (out of scope, see §11).
  - It injects the notify-client into HTML responses under `/p/` via `sub_filter`
    (`</body>` → `<script src="/lab/notify.js" defer></script></body>`; upstream gzip disabled with
    `proxy_set_header Accept-Encoding ""`). Projects don't have to know the orchestrator exists.
  - nginx config for `/p/<id>/` locations is **generated from the manifests** by a CLI step
    (`orchctl render-nginx`) at deploy time, followed by an nginx reload. Adding a project means
    dropping its folder in, then running the deploy/render step. No code change.
- **control-plane** (Python, FastAPI, uv): owns all state in **SQLite (WAL)**. It runs the lease/queue
  state machine, issues and validates session cookies, serves SSE event streams, sends optional
  emails, and exposes the **desired state** to the agent. It has no Docker access.
- **agent** (Python, uv): the only process with Docker socket access. It runs in a container with the
  socket mounted, **no published ports**, attached only to `orch-internal` (plus whatever it needs to
  reach stacks' health endpoints). It's a **reconciler**: it long-polls control-plane for desired
  state (`{active: <id>|null, generation: n}`), converges the box to it (compose down anything else,
  compose up the desired stack, poll health), and reports observed state back
  (`starting | ready | failed | stopped`, with timestamps and errors). It's idempotent and
  restart-safe: after a crash it reads desired state and re-converges. The "desired vs observed state"
  model is part of the portfolio story.
- **orchestrator UI** (`apps/lab`, Vite + React + TS, pnpm): the showcase front end. It shows a project
  catalog (from manifests, via the API), live status of the box, the queue, the per-project
  interstitial, and the explanatory copy. It consumes `packages/design-system` when that exists.
- **notify-client** (`packages/notify-client`, tiny dependency-free JS): injected into project pages.
  It opens the SSE stream, renders toasts/banners for lease events, and sends **activity beats**.

## 6. Lease, queue, and grace (carried over from July, adapted for no-login)

Identity is an **anonymous session**: a signed, httpOnly, SameSite=Lax cookie (`orch_sid`) on the
single domain, minted on first visit. The holder and queue entries are keyed by session id. Optional
email is attached to the session.

Rules:
- **Start** when the box is idle: the requester becomes holder immediately, and the stack starts.
- **Start** when the box is busy: the requester is appended to a **global FIFO queue** (one entry per
  session). There's no "jump the queue". Starting a stack never tears down someone's protected window.
- **Protected window:** the holder gets **15 min** from `ready` (not from request). It's never
  interrupted during that window, except by the holder.
- **Empty queue:** the stack is **not** torn down at expiry. It runs indefinitely until someone queues.
- **Contention:** when someone is queued and the holder's window has expired (or as soon as it
  expires), the holder enters a **3-min grace** with a notification in whatever app they're in. At the
  end of grace: teardown, then auto-start the head of the queue's stack. Max hold under contention is
  about 18 min.
- **Idle holder** (builder's call on thresholds, suggested: no activity beat for 3 min while someone is
  queued): the remaining protected window is forfeited and grace starts immediately. "Idle" means
  genuinely no interaction (mousemove/keydown/click/focus/visibilitychange, debounced into beats,
  sent at most every 30s), never a passive timer.
- **Manual stop:** holder-only (session must match). Anyone else gets 403 and can only queue.
  The reaper (state machine timer) is the only other actor that may tear down, and only under
  contention or failure.
- **Queue presence:** a queued entry stays valid while its session has an open SSE connection **or**
  an email attached. An entry with neither for > 2 min is dropped. When an emailed-but-absent visitor
  reaches the head, their stack starts and they get an email. Their protected window still starts at
  `ready`, but the idle-holder rule applies, so an absent holder doesn't block the queue for long.
- **Queue display:** entries are shown under anonymized Docker-style aliases using Silicon Valley
  figure names (e.g. `pensive_hopper`). The viewer's own entry is marked `(Me)`.
- **Failure:** boot that exceeds the manifest's `health.timeout_s` is marked `failed`. The agent runs
  compose down, the holder is notified (with the demo link), the lease is released, and the next in
  queue starts. A ready stack whose health check fails N consecutive times (suggested 3) gets one
  automatic restart, then `failed` as above.
- **Abuse limits:** per-IP and per-session rate limits on start/queue (builder's call on numbers).
  The lease rules already bound how long any one visitor can hold the box.

- **Holder switching projects** *(designer's call)*: the holder may switch to another project in
  place. It's a teardown + start, and they keep the **remaining** protected window (no reset, so
  switching can't be used to extend a hold). The window clock pauses during the boot. A holder cannot
  also join the queue; switching is how they try another project.

- **Single-user access** (decided 2026-11-15): only the holder can use the running stack. Everyone
  else, including visitors who want the project that's already running, sees the interstitial
  ("in use by `pensive_hopper`, you're #2, ~N min") and queues. The reason is performance: ML apps on
  2 vCPU may not handle concurrent users, and a guaranteed-fast solo demo beats a slow shared one.
  *(Designer's call)* When the next queued entry wants the **same project** that's already running,
  the lease transfers without a teardown/restart.
- **Designed for sharing later:** access is decided by one policy function
  (`can_access(session, stack, state)`). Sharing would be added as a per-manifest
  `access = "holder" | "shared"` (with an optional `max_viewers`) without reworking the state machine.
  This is **not built now**.

The state machine is a **pure module** (events in, new state plus effects out; injected clock) with
exhaustive unit tests. The service layer just persists state and executes effects.

### Notification events (SSE, per session)

`queue_changed`, `your_turn`, `stack_starting`, `stack_ready`, `grace_started` (with deadline),
`evicted`, `stack_failed`. Each carries machine fields plus human copy that explains the reason.

### Email (optional)

The visitor can attach an email in the queue/interstitial UI. It's used only for `your_turn` /
`stack_ready` / `stack_failed` when they're not connected. It's sent through a transactional provider
(suggested: Resend free tier), with the API key in env. Emails are stored with the session and visible
to the owner in the admin view (below). The UI states plainly what the email is used for.

### Owner admin

`/lab/admin`, protected by a single owner secret (env var, checked server-side, separate cookie).
Force-stop, clear queue, view sessions/emails/visit log, view agent observed state and last errors.

## 7. Project contract (what every project must provide)

Each project is a folder `projects/<id>/` (it can be a git submodule or symlink to the project's own
repo) containing:

```toml
# projects/<id>/stack.toml
id = "rag-pipeline"                 # url-safe, unique; becomes /p/rag-pipeline/
name = "RAG Pipeline"
tagline = "Retrieval-augmented QA over …"
compose = "docker-compose.yml"      # relative to this folder
entry = { service = "web", port = 8000 }   # what nginx proxies /p/<id>/ to
health = { path = "/healthz", timeout_s = 180, interval_s = 3 }  # relative to entry
expected_boot_s = 90                # shown as ETA on the interstitial
demo_url = "https://…"              # always-available recorded walkthrough
order = 10                          # catalog ordering
```

Requirements on the project:
1. **Runs under a sub-path.** All URLs must be relative or base-path aware (Vite `base`, FastAPI
   `root_path`, no hard-coded `/api` or `/static`). nginx strips nothing and forwards
   `X-Forwarded-Prefix: /p/<id>`, so the app serves under `/p/<id>/`.
2. **Health endpoint** that returns 200 only when the app can really serve a user request
   (models loaded, DB migrated).
3. **Entry service joins the external docker network `orch-stacks`** with the alias `<id>-entry`, so
   nginx and the agent can reach it. Nothing in the compose publishes host ports.
4. Stateless or self-contained volumes. `compose down` (no `-v`) must be safe to run at any time.
5. Returns HTML with a `</body>` tag if it wants the injected notify-client. Otherwise it may include
   `/lab/notify.js` manually, or go without notifications.

**Images are built ahead of time, never at visitor time** *(designer's call)*. A deploy step
(`orchctl prepare`) runs `docker compose build` / `pull` for every manifest. The agent always runs
`compose up --no-build`, so `expected_boot_s` and `health.timeout_s` measure boot only. If a needed
image is missing, the agent reports `failed` with a clear error rather than building on the box.

**Scope** *(designer's call)*: adapting the real ML projects to this contract is **out of scope**.
"Done" means the orchestrator works end to end with the two example projects, plus a written
onboarding checklist (`docs/adding-a-project.md`) that real projects follow later.

The repo ships **two dummy example projects** (`projects/_examples/fast` and `projects/_examples/slow`,
e.g. a tiny HTTP server whose health endpoint turns green after N seconds). They're used for
integration tests and as templates. Projects whose folder name starts with `_` are hidden from the
public catalog unless enabled by config.

## 8. Approaches considered

- **A. Custom control plane + host agent driving docker compose, manifest per project (CHOSEN).**
  Full control over the exclusivity, lease, queue and grace behaviour. The orchestrator is a
  showcase project, so building it is the point.
- **B. Off-the-shelf scale-to-zero (Sablier + Traefik) with a thin control plane.** Boot-on-request
  works for free, but it has no mutual exclusion, queue or lease, so we'd be fighting the tool. It's
  also a weaker portfolio story. We borrowed its "proxy shows a booting page" idea.
- Rejected outright: **k3s / Nomad** (they use about 0.5 vCPU idle on a 2-vCPU box), and
  **control plane with direct socket access** (violates the security boundary).

Decisions made in conversation (2026-11-15):
- Approach A.
- **nginx** (not Caddy), **single domain**, path-based routing.
- **No login**. Email optional.
- The July decisions (lease/queue/grace, socket isolation, readiness, activity beats, anonymized
  queue, copy-as-deliverable) still stand.

## 9. Repo layout and tooling

Monorepo at the repo root (per existing tooling conventions):

```
apps/lab/                     # orchestrator UI (Vite react-ts, pnpm)
services/control-plane/       # FastAPI, SQLite  (uv workspace member)
services/agent/               # reconciler       (uv workspace member)
packages/notify-client/       # injected JS
packages/design-system/       # (separate workstream; lab consumes it when ready)
infra/nginx/                  # base config + templates rendered from manifests
infra/compose.yml             # nginx + control-plane + agent + networks
projects/                     # manifests (+ _examples)
docs/
```

Python: uv workspace, pinned Python, ruff + mypy. JS/TS: pnpm, pinned Node LTS, ESLint + Prettier,
strict TS. Root pre-commit with a secrets scanner. CI runs the same checks plus tests.

## 10. Testing

- State machine: exhaustive unit tests with a fake clock. Every rule in §6 has at least one test,
  including contention at and after expiry, idle forfeit, grace, failure, queue presence drop,
  and holder-only stop.
- Agent: reconciler tests against a fake compose/health driver (idempotence, crash recovery,
  boot timeout).
- Integration: real docker with the two example projects. Covers start → ready → gate opens;
  second visitor queues → grace → handoff; boot timeout → failed → next starts.
- nginx: a smoke test that `/p/<id>/` redirects to the interstitial when not ready and proxies when
  ready, and that the notify script is injected.

## 11. Left to the builder

- Exact thresholds (idle, presence, health failure count, rate limits) within the suggestions above.
- Alias generation scheme, SSE heartbeat interval, schema details.
- Deploy mechanics on the Oracle box (TLS via certbot or similar, systemd vs compose restart policy).
- Visual design of `apps/lab`. Functional first, with the design-system pass later as its own
  workstream. The interstitial still needs ETA, demo link and copy from day one.
- What lives at `/` (personal portfolio site) is out of scope. nginx just leaves it unassigned.
