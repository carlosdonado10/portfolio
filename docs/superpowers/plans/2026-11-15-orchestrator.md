# Orchestrator ("the lab") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project-agnostic orchestrator that runs exactly one docker-compose stack at a time on a 2 vCPU box, hands it fairly between anonymous visitors (lease + queue + grace), and serves everything on one domain behind nginx.

**Architecture:** nginx is the only public process. A FastAPI **control-plane** owns all state (SQLite) and runs a **pure lease/queue state machine**. It never touches Docker. A separate **agent** (the only holder of the Docker socket) long-polls the control-plane for *desired state*, converges the box with `docker compose`, polls health, and reports *observed state*. Projects plug in through `projects/<id>/stack.toml`. nginx `/p/<id>/` locations are rendered from those manifests and gated by `auth_request`.

**Tech Stack:** Python 3.13 + uv workspace (FastAPI, uvicorn, pydantic v2, httpx, itsdangerous, stdlib sqlite3, pytest, pytest-asyncio, ruff, mypy); Node 24 LTS + pnpm 11 (Vite react-ts, vitest, Testing Library, ESLint, Prettier); nginx 1.27; Docker Compose v2.

**Spec:** `docs/superpowers/specs/2026-11-15-orchestrator-design.md`

## Global Constraints

- Build on the existing scaffold on `main` (ADRs 0001–0005): package names `control_plane` and `agent`, Python 3.13, Node 24, pnpm 11.17. Target **linux/arm64**: all images must be multi-arch.
- Per ADR 0005, project code lives in its own repos. This repo holds only manifests in `projects/`, plus in-repo examples. No submodules.
- Nothing internet-facing may access `/var/run/docker.sock`. Only the `agent` container mounts it. The agent publishes no ports.
- The control-plane is the **only** writer of SQLite.
- No login. Identity = signed, httpOnly, SameSite=Lax cookie `orch_sid`. Email is optional and only used for `your_turn` / `stack_ready` / `stack_failed` when not connected.
- Lease constants (defaults, configurable): protected window **900s** from `ready`, grace **180s**, idle forfeit **180s** without an activity beat (only while someone is queued), queue-presence drop **120s** (no SSE and no email), health failures before restart **3**.
- Single-user access: the gate admits only the holder's `orch_sid`.
- Projects are served at `/p/<id>/`; orchestrator UI at `/lab/`; public API at `/api/`; `/` is left unassigned.
- Project ids match `^[a-z0-9][a-z0-9-]{0,39}$`. Folders starting with `_` are hidden from the catalog unless `ORCH_INCLUDE_HIDDEN=1`.
- The agent always runs `docker compose up -d --no-build`. It never builds at visitor time.
- No orchestrator code may name a specific project.
- Every user-facing status/notification string explains the engineering reason (copy is a deliverable). Example: *"Booting rag-pipeline. The box has 2 CPUs, so only one project runs at a time; you'll get it to yourself for 15 minutes once it's serving."*
- Commits use Conventional Commits and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Stale agent report after a switch:** an `observed` report carrying an old `generation` must be ignored. Otherwise a new stack is marked `ready` before it serves. *(Test in Task 3.)*
2. **Control-plane restart mid-boot:** lease, queue, generation and the window clock must survive a restart, and the first tick after reload must not evict anyone wrongly. *(Test in Task 5.)*
3. **Unknown or hidden stack id** in `POST /api/start` gives 404, not a crash or a queued phantom. *(Test in Task 6.)*
4. **Cookie-less clients** (cookies blocked): `POST /api/start` without an existing `orch_sid` gives 400 with an explanatory message, so one client can't mint unlimited queue entries. *(Test in Task 6.)*
5. **Same session in several tabs:** every open SSE stream for a sid receives each event, and closing one tab doesn't drop the visitor from the queue while another is open. *(Test in Task 5.)*

---

## File Structure

```
pyproject.toml                       # uv workspace root + ruff/mypy/pytest config
.python-version  .nvmrc  package.json  pnpm-workspace.yaml  .pre-commit-config.yaml
services/common/src/orch_common/
    manifest.py      # Manifest model + load_manifests
    wire.py          # DesiredState, ObservedState, StackStatus (control-plane <-> agent)
    cli.py           # orchctl: validate | render-nginx | prepare
    nginx.py         # render_projects_conf()
services/control-plane/src/control_plane/
    lease.py         # PURE state machine: State, events, effects, decide()
    aliases.py       # alias_for(sid)
    copy.py          # notification/email copy
    store.py         # SQLite persistence
    hub.py           # per-sid SSE fan-out
    mailer.py        # Mailer protocol, ResendMailer, NullMailer
    engine.py        # Engine: lock, dispatch, effect execution, tick loop, desired-state long-poll
    ratelimit.py     # token buckets
    api_public.py    # /api/*, /internal/gate/*
    api_agent.py     # /agent/* (internal port only)
    settings.py  main.py   # existing app.py's /health is folded into api_public
services/agent/src/agent/
    driver.py        # ComposeDriver protocol + DockerComposeDriver
    probe.py         # HealthProbe protocol + HttpHealthProbe
    reconciler.py    # Reconciler
    client.py        # ControlPlaneClient (long-poll + report)
    __main__.py      # existing heartbeat stub replaced by the reconciler loop
packages/notify-client/              # injected notify.js (TS -> single IIFE)
apps/lab/                            # orchestrator UI (base /lab/), git mv from apps/landing
infra/proxy/nginx.conf  infra/proxy/generated/.gitkeep   # replaces the WS0.2 placeholder
docker-compose.yml                   # existing root compose (modified)
projects/_examples/fast/  projects/_examples/slow/
tests/integration/                   # docker-backed end-to-end
docs/adding-a-project.md
```

---

### Task 1: Align the existing scaffold

`main` already has the WS-P0.1 scaffold (ADRs 0001–0005): a uv virtual workspace (`services/control-plane` → package `control_plane`, `services/agent` → package `agent`), a pnpm 11 workspace (`apps/landing`, `packages/design-system`, `packages/notify-client` placeholder), Python 3.13, Node 24, a root `docker-compose.yml` and a `Makefile`. This task adapts it rather than re-scaffolding.

**Files:**
- Create: `services/common/pyproject.toml` (name `orch-common`, package `orch_common`, script `orchctl`), `services/common/src/orch_common/__init__.py`, `services/common/tests/test_smoke.py`
- Modify: root `pyproject.toml` (add `services/common` to members, add `[tool.ruff]`, `[tool.mypy] strict = true`, `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and marker `integration`), `services/control-plane/pyproject.toml` and `services/agent/pyproject.toml` (depend on `orch-common` via `[tool.uv.sources] orch-common = { workspace = true }`, add deps from Tech Stack, dev: pytest-asyncio, ruff, mypy)
- Move: `git mv apps/landing apps/lab`, rename the package to `@portfolio/lab`, and update the root `package.json` scripts and the `Makefile`
- Delete: `supabase/` and the Supabase block in `.env.example`. Update the Supabase comments in `docker-compose.yml`. Add a one-line "superseded by ADR 0006: no login" note to ADR 0005's auth item rather than rewriting it.
- Create: `.pre-commit-config.yaml` (ruff, ruff-format, mypy, gitleaks, end-of-file-fixer, trailing-whitespace, check-yaml, check-toml, conventional-pre-commit on commit-msg), `.github/workflows/ci.yml` (uv sync, ruff, mypy, pytest -m "not integration", pnpm install, pnpm -r lint test build)
- Modify: `.gitignore` (add `.venv/`, `*.sqlite*`, `infra/proxy/generated/*.conf`)
- Create: `docs/decisions/0006-orchestrator-no-login-single-domain.md` (records no login, nginx single domain, manifest registry + per-project repos)

**Interfaces:**
- Produces: packages `orch_common`, `control_plane`, `agent` importable via `uv run`. Existing tests (`test_health.py`, `test_heartbeat.py`) keep passing until later tasks replace them.

- [ ] **Step 1:** Write `services/common/tests/test_smoke.py`: `import orch_common, control_plane, agent` succeeds.
- [ ] **Step 2:** Run `uv run pytest services/common/tests/test_smoke.py` and expect FAIL (no `orch_common`).
- [ ] **Step 3:** Make the changes listed above.
- [ ] **Step 4:** Run `uv sync && uv run pytest && uv run ruff check . && uv run mypy services` and expect all to pass. Run `pnpm install && pnpm --filter @portfolio/lab build` and expect it to pass. `grep -rni supabase --exclude-dir=docs --exclude-dir=node_modules .` should return nothing.
- [ ] **Step 5:** Run `pre-commit run --all-files` and expect it to pass.
- [ ] **Step 6:** Commit `chore: align scaffold for orchestrator (common pkg, lab app, quality gates, drop supabase)`.

---

### Task 2: Manifest model and wire schemas

**Files:**
- Create: `services/common/src/orch_common/manifest.py`, `services/common/src/orch_common/wire.py`
- Test: `services/common/tests/test_manifest.py`, `services/common/tests/test_wire.py`

**Interfaces:**
- Produces:
  - `class Entry(BaseModel): service: str; port: int`
  - `class Health(BaseModel): path: str = "/healthz"; timeout_s: int = 180; interval_s: float = 3`
  - `class Manifest(BaseModel)` with fields `id, name, tagline: str = "", repo: str | None = None, ref: str = "main", compose: str, entry: Entry, health: Health, expected_boot_s: int, demo_url: str | None = None, order: int = 100`, plus non-serialized `dir: Path` and `hidden: bool`. Methods: `checkout_dir(repos_dir: Path) -> Path` (`repos_dir / id` if `repo` else `dir`) and `compose_path(repos_dir: Path) -> Path`. Properties: `base_path -> str` (`f"/p/{id}/"`), `project_name -> str` (`f"orch-{id}"`), `entry_alias -> str` (`f"{id}-entry"`).
  - `class ManifestError(Exception)`
  - `def load_manifests(projects_dir: Path, include_hidden: bool = False) -> list[Manifest]` scans `*/stack.toml` and `_*/**/stack.toml` (hidden), sorted by `(order, id)`.
  - `class StackStatus(StrEnum): STOPPED="stopped"; STARTING="starting"; READY="ready"; FAILED="failed"`
  - `class DesiredState(BaseModel): active: str | None; generation: int`
  - `class ObservedState(BaseModel): stack_id: str | None; status: StackStatus; generation: int; error: str | None = None; at: float`

- [ ] **Step 1: Write failing tests** (use `tmp_path` fixtures that write folders):
  - `test_loads_valid_manifest`: `m.id == "demo"`, `m.base_path == "/p/demo/"`, `m.project_name == "orch-demo"`, `m.health.timeout_s == 180` by default.
  - `test_rejects_bad_id`: id `"Bad_ID"` raises `ManifestError`.
  - `test_rejects_folder_id_mismatch`: folder `foo` with `id="bar"` raises `ManifestError`.
  - `test_rejects_missing_compose_file` raises `ManifestError` (checked only when `repo` is None; for repo-backed manifests, existence is checked by `orchctl prepare` and the agent).
  - `test_repo_manifest_paths`: with `repo` set, `m.compose_path(Path("/srv/r")) == Path("/srv/r/demo/docker-compose.yml")`.
  - `test_rejects_duplicate_ids` raises `ManifestError`.
  - `test_hidden_excluded_by_default`: `_examples/fast` is absent unless `include_hidden=True`; when included, `m.hidden is True`.
  - `test_sorted_by_order_then_id`.
  - `test_wire_roundtrip`: `ObservedState.model_validate_json(o.model_dump_json()) == o`.
- [ ] **Step 2:** Run `uv run pytest services/common/tests -v` and expect FAIL.
- [ ] **Step 3:** Implement the models and `load_manifests` in the files above (`tomllib`, pydantic `field_validator` for the id regex).
- [ ] **Step 4:** Run `uv run pytest services/common/tests -v` and expect PASS.
- [ ] **Step 5:** Commit `feat(common): manifest model, discovery, and agent wire schemas`.

---

### Task 3: Lease state machine — core flow

Pure module. No I/O, no clock reads, no randomness.

**Files:**
- Create: `services/control-plane/src/control_plane/lease.py`, `services/control-plane/src/control_plane/aliases.py`
- Test: `services/control-plane/tests/test_lease_core.py`, `services/control-plane/tests/test_aliases.py`

**Interfaces:**
- Consumes: `StackStatus` (Task 2).
- Produces (all `@dataclass(frozen=True)`):
  - `LeaseConfig(window_s=900, grace_s=180, idle_s=180, presence_s=120)`
  - `Lease(sid, alias, stack_id, has_email: bool, window_remaining_s: float, window_ends_at: float | None, last_activity: float, grace_deadline: float | None)`. `window_ends_at` is set only while `ready`, and `window_remaining_s` is the frozen remainder while not ready.
  - `QueueEntry(sid, alias, stack_id, has_email: bool, enqueued_at: float, last_seen: float)`
  - `State(lease: Lease | None = None, status: StackStatus = STOPPED, queue: tuple[QueueEntry, ...] = (), generation: int = 0)`, with `to_json() -> str` and `State.from_json(s) -> State`.
  - Events: `StartRequested(sid, stack_id, now, has_email=False)`, `StopRequested(sid, now)`, `Observed(stack_id, status, generation, now, error=None)`, `Activity(sid, now)`, `Seen(sid, now)` (SSE heartbeat/connection), `EmailAttached(sid, now)`, `Tick(now)`, `AdminForceStop(now)`, `AdminClearQueue(now)`; `Event = Union[...]`.
  - Effects: `SetDesired(stack_id: str | None, generation: int)`, `Notify(sid, kind: str, data: dict)`, `Broadcast(kind: str)` (always `"queue_changed"`), `Email(sid, kind: str, stack_id: str)`.
  - `Transition(state: State, effects: tuple[Effect, ...])`
  - `class Rejected(Exception): status: int; reason: str` (copy text)
  - `def decide(state: State, event: Event, cfg: LeaseConfig) -> Transition`
  - `def alias_for(sid: str) -> str` deterministically maps sha256(sid) to `"{adjective}_{surname}"` from fixed lists of ≥30 adjectives and ≥30 Silicon Valley figure surnames (e.g. `hopper`, `lovelace`, `noyce`, `wozniak`, `moore`).

Rules this task implements (the spec §6 core):
- Idle box + `StartRequested`: the requester becomes holder (`window_remaining_s=cfg.window_s`), `status=STARTING`, `generation+1`. Effects: `SetDesired`, `Notify(holder,"stack_starting")`, `Broadcast`.
- Busy box + non-holder `StartRequested`: append to queue (or update `stack_id` if already queued). Effects: `Notify(sid,"queue_changed")`, `Broadcast`.
- Holder `StartRequested` with the same stack does nothing (empty effects).
- `Observed` with `generation != state.generation` is ignored (no-op).
- `Observed(READY)` for the active stack: `status=READY`, `window_ends_at = now + window_remaining_s`, `last_activity = now`. Effects: `Notify(holder,"stack_ready")`, plus `Email(holder,"stack_ready")` if `has_email`.
- `Observed(STOPPED)` while desired is `None`: `status=STOPPED`.
- `StopRequested` by a non-holder raises `Rejected(403, ...)`. By the holder, it releases and promotes (below).
- **Contention** (evaluated at the end of every `decide`): if lease, queue non-empty, `status==READY`, no grace, and `now >= window_ends_at`, then `grace_deadline = now + cfg.grace_s`, `Notify(holder,"grace_started",{"deadline":...})`.
- `Tick(now >= grace_deadline)`: `Notify(old,"evicted")`, then promote.
- Empty queue: no grace ever starts, and the stack keeps running past window expiry.
- **Promote:** pop the queue head. It becomes holder with a fresh `cfg.window_s`. If `head.stack_id == current stack_id and status == READY`: keep `READY`, `window_ends_at = now + cfg.window_s`, no `SetDesired`, and emit `Notify(head,"your_turn")` + `Notify(head,"stack_ready")`. Otherwise: `status=STARTING`, `generation+1`, `SetDesired(head.stack_id)`, `Notify(head,"your_turn")`, `Notify(head,"stack_starting")`, and `Email(head,"your_turn")` if `has_email`. If the queue is empty: `lease=None`, `generation+1`, `SetDesired(None)`. Always `Broadcast`.

- [ ] **Step 1: Write failing tests** (helper `run(state, *events) -> (State, list[Effect])` folds `decide`; `CFG = LeaseConfig()`):
  - `test_idle_start_makes_holder_and_sets_desired`: status STARTING, generation 1, effects contain `SetDesired("a", 1)`.
  - `test_second_visitor_queues`: `len(queue)==1`, lease sid unchanged, no new `SetDesired`.
  - `test_requeue_updates_stack_not_duplicates`.
  - `test_holder_same_stack_is_noop`.
  - `test_stale_generation_observed_ignored`: after a switch to generation 2, `Observed("a", READY, generation=1)` leaves status STARTING. *(Review Focus 1)*
  - `test_ready_starts_window_from_ready_not_request`: start at t=0, ready at t=100, so `window_ends_at == 1000`.
  - `test_no_grace_when_queue_empty_even_after_expiry`: tick at t=5000, `grace_deadline is None`, and lease intact.
  - `test_queue_after_expiry_starts_grace_immediately`: ready at 0, B queues at 2000, so `grace_deadline == 2180` and `Notify(A,"grace_started")` is emitted.
  - `test_queue_before_expiry_grace_at_window_end`: B queues at 100, tick at 899 gives no grace, and tick at 900 gives `grace_deadline == 1080`.
  - `test_protected_window_never_interrupted`: B queues at 1, ticks every 100s up to 899, and no `grace_started`/`evicted` appears.
  - `test_grace_end_evicts_and_promotes_different_stack`: `Notify(A,"evicted")`, holder B, `SetDesired("b", gen+1)`, status STARTING.
  - `test_promote_same_stack_transfers_without_restart`: B wanted "a", so no `SetDesired`, status READY, and the B window is 900 from now.
  - `test_non_holder_stop_rejected_403`.
  - `test_holder_stop_with_empty_queue_sets_desired_none`.
  - `test_holder_stop_promotes_next`.
  - `test_ready_emails_holder_with_email`.
  - `test_state_json_roundtrip`.
  - `test_alias_deterministic_and_well_formed`: same sid gives the same alias, matching `^[a-z]+_[a-z]+$`.
- [ ] **Step 2:** Run `uv run pytest services/control-plane/tests/test_lease_core.py -v` and expect FAIL.
- [ ] **Step 3:** Implement `decide` as a dispatch on event type, with private helpers `_promote(state, now, cfg)` and `_evaluate_contention(state, now, cfg)`. Use `dataclasses.replace` for updates.
- [ ] **Step 4:** Run the tests and expect PASS. `uv run mypy services/control-plane` should be clean.
- [ ] **Step 5:** Commit `feat(control-plane): pure lease/queue/grace state machine core`.

---

### Task 4: Lease state machine — idle, presence, failure, switching, admin

**Files:**
- Modify: `services/control-plane/src/control_plane/lease.py`
- Test: `services/control-plane/tests/test_lease_edges.py`

**Interfaces:**
- Consumes/Produces: same types as Task 3. New notify kind: `"grace_cancelled"`.

Rules:
- `Activity(sid)`: holder updates `last_activity`, queued entry updates `last_seen`. `Seen(sid)`: queued entry updates `last_seen` (it doesn't count as holder activity).
- **Idle forfeit:** in `_evaluate_contention`, also start grace when queue non-empty, `status==READY`, and `now - last_activity >= cfg.idle_s`, even inside the window.
- **Grace cancel:** if the queue becomes empty while `grace_deadline` is set, clear it and emit `Notify(holder,"grace_cancelled")`.
- **Presence drop:** on `Tick`, remove entries with `not has_email and now - last_seen > cfg.presence_s`, and `Broadcast` if any were removed.
- `EmailAttached(sid)` sets `has_email=True` on the holder or the queue entry.
- `Observed(FAILED)` for the active generation: `Notify(holder,"stack_failed",{"error":...})`, plus `Email(holder,"stack_failed")` if `has_email`, then promote (a failed stack never transfers. Promote with status FAILED takes the restart branch).
- **Switch:** holder `StartRequested` with a different stack. If `grace_deadline` is set, raise `Rejected(409, ...)`. Otherwise `window_remaining_s = max(0, window_ends_at - now)` if READY (else keep the frozen value), set `window_ends_at=None`, `status=STARTING`, `generation+1`, and emit `SetDesired(new)` + `Notify(holder,"stack_starting")`.
- No grace or idle checks while `status != READY` (the boot clock is paused).
- `AdminForceStop`: `Notify(holder,"evicted")` then promote. `AdminClearQueue`: empty the queue, emit `Notify(sid,"queue_changed")` for each removed entry, and `Broadcast`.

- [ ] **Step 1: Write failing tests:**
  - `test_idle_holder_forfeits_when_someone_queued`: ready at 0, last activity 0, B queues at 10, tick at 180 gives `grace_deadline == 360`.
  - `test_idle_holder_kept_when_queue_empty`: tick at 5000 gives no grace.
  - `test_activity_resets_idle`: Activity(A) at 170 and tick at 200 gives no grace.
  - `test_seen_does_not_count_as_holder_activity`.
  - `test_grace_cancelled_when_queue_empties`: B dropped for presence, so `grace_deadline is None` and `Notify(A,"grace_cancelled")`.
  - `test_presence_drop_without_email`: B last_seen 0 and tick 121 removes B.
  - `test_presence_kept_with_email`: tick 10_000 keeps B.
  - `test_failed_boot_notifies_emails_and_promotes`.
  - `test_failed_with_same_stack_queued_restarts_not_transfers`: `SetDesired` is emitted.
  - `test_switch_keeps_remaining_window`: ready at 0, switch at 600, ready at 700, so `window_ends_at == 1000`.
  - `test_switch_during_grace_rejected_409`.
  - `test_no_grace_while_starting`: after the switch at 600, B queued and tick at 950 (still STARTING) gives no grace.
  - `test_admin_force_stop_promotes`, `test_admin_clear_queue`.
- [ ] **Step 2:** Run `uv run pytest services/control-plane/tests/test_lease_edges.py -v` and expect FAIL.
- [ ] **Step 3:** Implement the rules in `lease.py`.
- [ ] **Step 4:** Run `uv run pytest services/control-plane -v` and expect PASS (core + edges).
- [ ] **Step 5:** Commit `feat(control-plane): idle forfeit, presence, failure, switching, admin transitions`.

---

### Task 5: Persistence, hub, mailer, and the Engine

**Files:**
- Create: `control_plane/store.py`, `control_plane/hub.py`, `control_plane/mailer.py`, `control_plane/copy.py`, `control_plane/engine.py`, `control_plane/settings.py`
- Test: `services/control-plane/tests/test_store.py`, `test_hub.py`, `test_engine.py`

**Interfaces:**
- Consumes: `lease.*` (Tasks 3–4), `DesiredState`, `ObservedState`, `Manifest`.
- Produces:
  - `class Store(path: Path)`: `load_state() -> State` (default `State()`), `save_state(State) -> None`, `ensure_session(sid: str, ip: str) -> None`, `set_email(sid, email) -> None`, `get_email(sid) -> str | None`, `log_visit(sid, path, at) -> None`, `list_sessions() -> list[dict]`. Tables: `state(id=1, json)`, `sessions(sid PK, email, ip, created_at)`, `visits(sid, path, at)`. WAL mode.
  - `class Hub`: `subscribe(sid) -> AsyncIterator[dict]` (an async context manager yielding a queue iterator), `publish(sid, msg: dict) -> None`, `broadcast(msg: dict) -> None`, `connected(sid) -> bool`. Multiple subscribers per sid.
  - `class Mailer(Protocol): async def send(to: str, subject: str, body: str) -> None`. `NullMailer` (logs), `ResendMailer(api_key, from_addr)` (POST `https://api.resend.com/emails` via httpx).
  - `copy.py`: `def notification(kind: str, stack_name: str, data: dict) -> dict[str, str]` returns `{"title", "body"}` for kinds `queue_changed, your_turn, stack_starting, stack_ready, grace_started, grace_cancelled, evicted, stack_failed`. `def email(kind, stack_name, link) -> tuple[str, str]`. Every body states the reason (see Global Constraints).
  - `Settings` (pydantic-settings, env prefix `ORCH_`): `db_path, projects_dir, include_hidden=False, cookie_secret, cookie_secure=True, owner_secret, resend_api_key=None, email_from=None, public_base_url, repos_dir=/srv/orch/repos, lease: LeaseSettings` (a pydantic model mirroring `LeaseConfig`, with `.to_config()`; `env_nested_delimiter="__"`, so `ORCH_LEASE__WINDOW_S=5` works).
  - `class Engine(store, hub, mailer, manifests: dict[str, Manifest], cfg: LeaseConfig, clock: Callable[[], float] = time.time)`:
    - `state: State` (property)
    - `async def dispatch(event: Event) -> State`: under `asyncio.Lock`, calls `decide` (letting `Rejected` propagate), saves state, then executes effects. `SetDesired` wakes desired-state waiters. `Notify` publishes `{"type": kind, **data, **copy.notification(...)}` to the sid. `Broadcast` sends `{"type":"queue_changed"}` to all. `Email` sends only if an email is stored and `not hub.connected(sid)` (or always for `your_turn`).
    - `async def wait_desired(after_generation: int, timeout: float) -> DesiredState`
    - `def desired() -> DesiredState` (derived: `active = lease.stack_id if lease else None`)
    - `async def run_ticks(interval: float = 1.0) -> None` (dispatches `Tick(clock())` forever)
    - `@classmethod def load(...) -> Engine` (restores state from store)

- [ ] **Step 1: Write failing tests:**
  - `test_store_state_roundtrip` and `test_store_email`.
  - `test_hub_fanout_to_all_tabs`: two subscribers for the same sid both receive the published msg. *(Review Focus 5)*
  - `test_hub_connected_until_last_tab_closes`.
  - `test_engine_dispatch_persists_and_notifies`: after a start, `store.load_state().lease.sid == "s1"` and the subscriber got `type == "stack_starting"` with non-empty `body`.
  - `test_engine_wait_desired_wakes_on_change`: a waiter at generation 0 returns `active == "a"` after a start dispatch.
  - `test_engine_restart_preserves_state_and_clock`: start, ready at t=0 with a fake clock, B queued, rebuild via `Engine.load` on the same db, tick at 100 gives the same lease, no eviction, generation unchanged. *(Review Focus 2)*
  - `test_email_sent_when_not_connected` / `test_email_skipped_when_connected` (fake Mailer records calls).
  - `test_every_kind_has_copy`: for each kind, `notification(kind, "X", {})["body"]` is non-empty.
- [ ] **Step 2:** Run `uv run pytest services/control-plane -v` and expect FAIL.
- [ ] **Step 3:** Implement the modules above.
- [ ] **Step 4:** Run the tests and expect PASS.
- [ ] **Step 5:** Commit `feat(control-plane): sqlite store, SSE hub, mailer, engine`.

---

### Task 6: Public API, sessions, gate, rate limits, admin

**Files:**
- Create: `control_plane/api_public.py`, `control_plane/ratelimit.py`
- Test: `services/control-plane/tests/test_api_public.py`

**Interfaces:**
- Consumes: `Engine`, `Store`, `Settings`, `Manifest`.
- Produces `def create_public_app(engine: Engine, store: Store, settings: Settings) -> FastAPI` with:
  - Session middleware: if `orch_sid` (itsdangerous-signed) is missing or invalid on a **GET**, mint `secrets.token_urlsafe(24)` and set the cookie (`httponly`, `samesite=lax`, `secure=settings.cookie_secure`, path `/`, max-age 30d). State-changing **POSTs without a valid cookie give 400** `{"detail": <copy explaining cookies are needed to hold your place>}`. *(Review Focus 4)*
  - `GET /api/projects` returns `[{id, name, tagline, base_path, expected_boot_s, demo_url}]` (hidden excluded unless `include_hidden`).
  - `GET /api/status` returns `{active: id|null, status, holder_alias, window_ends_at, grace_deadline, queue: [{alias, stack_id, me: bool}], me: {role: "holder"|"queued"|"none", position: int|null, alias}}`.
  - `POST /api/start {stack_id}` gives 404 for an unknown or hidden id *(Review Focus 3)*, maps `Rejected` to its status, 429 from the rate limit, and 200 with status otherwise.
  - `POST /api/stop`, `POST /api/activity` (204), `POST /api/email {email}` (validates with pydantic `EmailStr`, stores it, dispatches `EmailAttached`).
  - `GET /api/events` is an SSE stream (`text/event-stream`). On connect it dispatches `Seen`, sends a `: ping` comment plus a `Seen` dispatch every 15s, and forwards hub messages as `data: <json>`.
  - `GET /internal/gate/{stack_id}` returns 204 iff `state.lease.stack_id == stack_id and status == READY and sid == lease.sid`, else 401. It reads the cookie from the request. nginx exposes it only as an internal location.
  - Admin: `POST /api/admin/login {secret}` (constant-time compare against `owner_secret`, sets the signed `orch_admin` cookie), `POST /api/admin/force-stop`, `POST /api/admin/clear-queue`, `GET /api/admin/overview` (state, sessions with emails, recent visits). 401 without the admin cookie.
  - `class TokenBucket(rate_per_min: int)` with `allow(key: str, now: float) -> bool`. Limits on `/api/start`: 10/min per IP (`X-Real-IP` header), 5/min per sid.

- [ ] **Step 1: Write failing tests** (httpx `AsyncClient` + `ASGITransport`, temp db, fake clock, manifests `a`, `b`, `_hidden`):
  - `test_get_mints_cookie`.
  - `test_post_without_cookie_400`.
  - `test_start_unknown_404` and `test_start_hidden_404`.
  - `test_start_then_status_shows_holder_me`.
  - `test_second_client_queued_with_position_and_me_flag`: B sees `me.role=="queued"`, `position==1`, and its own entry `me: true`. The holder alias is not B's.
  - `test_gate_only_holder_when_ready`: before ready gives 401, after `Observed(READY)` the holder gets 204 and B gets 401.
  - `test_stop_by_non_holder_403`.
  - `test_rate_limit_429`: the sixth start in a minute from one sid gives 429.
  - `test_email_invalid_422`, `test_email_attaches`.
  - `test_sse_receives_notification`: open `/api/events`, dispatch a start for this sid, and read one `data:` line with `type == "stack_starting"`.
  - `test_admin_requires_secret`, `test_admin_force_stop`.
- [ ] **Step 2:** Run `uv run pytest services/control-plane/tests/test_api_public.py -v` and expect FAIL.
- [ ] **Step 3:** Implement `create_public_app` and `TokenBucket`.
- [ ] **Step 4:** Run the tests and expect PASS.
- [ ] **Step 5:** Commit `feat(control-plane): public API, sessions, gate, rate limits, admin`.

---

### Task 7: Agent API and control-plane entrypoint

**Files:**
- Create: `control_plane/api_agent.py`, `control_plane/main.py`, `services/control-plane/Dockerfile`
- Test: `services/control-plane/tests/test_api_agent.py`

**Interfaces:**
- Produces `def create_agent_app(engine: Engine) -> FastAPI`:
  - `GET /agent/desired?after_generation=<int>` long-polls (25s) via `engine.wait_desired` and returns `DesiredState`.
  - `POST /agent/observed` with an `ObservedState` body dispatches `Observed(...)`, returns 204, and the engine ignores stale generations.
  - `GET /agent/manifests` returns the manifest ids it knows (sanity check for drift).
- `main.py`: builds `Settings`, `Engine.load`, and runs **two** uvicorn servers in one asyncio loop: the public app on `0.0.0.0:8000` and the agent app on `0.0.0.0:8001` (8001 is reachable only on `orch-internal`, never proxied by nginx). It also runs `engine.run_ticks()`.
- Dockerfile: `python:3.13-slim` with uv, non-root user, `CMD ["uv","run","python","-m","control_plane.main"]`.

- [ ] **Step 1: Write failing tests:** `test_desired_long_poll_returns_on_change`, `test_desired_returns_current_immediately_if_newer`, `test_observed_ready_updates_state`, `test_observed_stale_generation_ignored`.
- [ ] **Step 2:** Run the tests and expect FAIL.
- [ ] **Step 3:** Implement the agent app and `main.py`.
- [ ] **Step 4:** Run `uv run pytest services/control-plane -v` and expect PASS.
- [ ] **Step 5:** Commit `feat(control-plane): internal agent API and dual-server entrypoint`.

---

### Task 8: Agent reconciler

**Files:**
- Create: `services/agent/src/agent/{driver,probe,reconciler,client,main}.py`, `services/agent/Dockerfile`
- Test: `services/agent/tests/test_reconciler.py`

**Interfaces:**
- Consumes: `Manifest`, `load_manifests`, `DesiredState`, `ObservedState`, `StackStatus`.
- Produces:
  - `class ComposeDriver(Protocol)`: `async up(m: Manifest) -> None`, `async down(m: Manifest) -> None`, `async running() -> set[str]` (ids with running containers).
  - `DockerComposeDriver` runs `docker compose -p orch-<id> -f <compose_path(repos_dir)> up -d --no-build --remove-orphans` / `down --remove-orphans` (never `-v`), and `running()` via `docker compose ls --format json` filtered to the `orch-` prefix. A non-zero exit raises `ComposeError(stderr)`. If an image is missing, the error reads like *"image not built — run `orchctl prepare`"*.
  - `class HealthProbe(Protocol)`: `async check(m: Manifest) -> bool`. `HttpHealthProbe` GETs `http://<entry_alias>:<port><base_path rstrip "/"><health.path>` with a 2s timeout and treats 200 as healthy.
  - `class Reconciler(manifests: dict[str, Manifest], driver, probe, report: Callable[[ObservedState], Awaitable[None]], clock, sleep)`:
    - `async converge(desired: DesiredState) -> None`: downs every running `orch-*` project that isn't `desired.active`. If `active` is None, reports STOPPED. Otherwise it reports STARTING, calls `up`, polls `probe` every `health.interval_s` until healthy (report READY) or `health.timeout_s` elapses (`down`, report FAILED with error). Every report carries `desired.generation`. If a newer desired generation arrives mid-boot, the current converge is cancelled.
    - `async watch_health(desired) -> None`: while READY, probes every 10s. After **3** consecutive failures it restarts once (`down`/`up`/poll). If that also fails, it reports FAILED.
  - `ControlPlaneClient(base_url)`: `async next_desired(after: int) -> DesiredState`, `async report(o: ObservedState) -> None`, with retry and backoff (1s up to 30s) on connection errors.
  - `main.py`: loop `desired = await client.next_desired(gen)`, then cancel the previous task and spawn `converge` then `watch_health`. On startup it fetches current desired with `after_generation=-1` and converges (crash recovery).

- [ ] **Step 1: Write failing tests** (FakeDriver records calls, ScriptedProbe returns a scripted sequence, fake clock + instant sleep):
  - `test_converge_starts_and_reports_ready`: reports `[STARTING, READY]` with generation 7.
  - `test_converge_downs_other_running_first`: `down("b")` is called before `up("a")`.
  - `test_converge_none_downs_all_reports_stopped`.
  - `test_boot_timeout_downs_and_reports_failed`: the error mentions the timeout.
  - `test_compose_error_reports_failed_with_message`.
  - `test_idempotent_when_already_running_and_healthy`: no `up` call, reports READY.
  - `test_newer_generation_cancels_boot`: no READY report for the old generation.
  - `test_health_watch_restarts_once_then_fails`.
  - `test_unknown_stack_reports_failed` (desired names an id the agent has no manifest for, i.e. drift).
- [ ] **Step 2:** Run `uv run pytest services/agent -v` and expect FAIL.
- [ ] **Step 3:** Implement the agent modules. Dockerfile: `python:3.13-slim` + docker CLI and compose plugin + uv, `CMD ["uv","run","python","-m","agent"]`.
- [ ] **Step 4:** Run `uv run pytest services/agent -v` and expect PASS.
- [ ] **Step 5:** Commit `feat(agent): desired-state reconciler with health watch`.

---

### Task 9: `orchctl` and nginx rendering

**Files:**
- Create: `services/common/src/orch_common/cli.py`, `services/common/src/orch_common/nginx.py`. Add the `[project.scripts] orchctl = "orch_common.cli:main"` entry.
- Test: `services/common/tests/test_nginx.py`, `services/common/tests/test_cli.py`

**Interfaces:**
- Produces `def render_projects_conf(manifests: list[Manifest]) -> str`, emitting one block per manifest:

```nginx
location /p/<id>/ {
    auth_request /_gate/<id>;
    error_page 401 = @interstitial_<id>;
    set $up_<id> http://<id>-entry:<port>;
    proxy_pass $up_<id>;
    proxy_set_header X-Forwarded-Prefix /p/<id>;
    include /etc/nginx/snippets/project-proxy.conf;
}
location = /_gate/<id> {
    internal;
    proxy_pass http://control-plane:8000/internal/gate/<id>;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Cookie $http_cookie;
}
location @interstitial_<id> { return 302 /lab/p/<id>; }
```
  (A variable `proxy_pass` plus `resolver 127.0.0.11 valid=10s` in the base config lets nginx start while stacks are down.)
- CLI (argparse): `orchctl validate [--projects DIR]` (exit 1 with the message on `ManifestError`), `orchctl render-nginx --out PATH`, and `orchctl prepare [--repos DIR]` (default `$ORCH_REPOS_DIR` or `/srv/orch/repos`; for each manifest with `repo`: `git clone` if missing, else `git fetch`, then `git checkout --detach <ref>`; then for every manifest `docker compose -f <compose_path> build` and `pull --ignore-buildable`, streaming output and exiting non-zero on failure).

- [ ] **Step 1: Write failing tests:** `test_render_contains_location_gate_and_interstitial_per_manifest`, `test_render_is_deterministic`, `test_validate_exit_codes` (good dir gives 0, bad id gives 1 with the message on stderr).
- [ ] **Step 2:** Run the tests and expect FAIL.
- [ ] **Step 3:** Implement the renderer and CLI.
- [ ] **Step 4:** Run the tests and expect PASS.
- [ ] **Step 5:** Commit `feat(common): orchctl validate/render-nginx/prepare`.

---

### Task 10: notify-client

**Files:**
- Create: `packages/notify-client/{package.json,tsconfig.json,vite.config.ts,src/index.ts,src/beats.ts,src/toast.ts,src/index.test.ts}`

**Interfaces:**
- Consumes: `GET /api/events` (SSE), `POST /api/activity`, message shape `{type, title, body, deadline?, ...}`.
- Produces: `dist/notify.js`, a single IIFE built in Vite library mode, with no dependencies and ≤ 8 KB gzipped. Exports for tests: `createBeatSender(post: () => void, intervalMs = 30000, now = Date.now)` returns `{onActivity(): void}`, and `renderToast(root: ShadowRoot, msg) -> HTMLElement`. On load it attaches a shadow-root host `<orch-notify>`, opens an `EventSource("/api/events")`, listens to `mousemove keydown click focus visibilitychange(visible)`, and renders toasts. `grace_started` shows a live countdown to `deadline` and a link to `/lab/`. Toasts are polite `role="status"` live regions, except `grace_started`/`evicted` which use `role="alert"`.

- [ ] **Step 1: Write failing tests** (vitest + jsdom): `beats_throttled_to_one_per_interval` (100 activity events in 10s give 1 post, and one more after 30s gives 2), `toast_renders_title_and_body`, `grace_toast_shows_countdown_and_alert_role`.
- [ ] **Step 2:** Run `pnpm --filter notify-client test` and expect FAIL.
- [ ] **Step 3:** Implement the client.
- [ ] **Step 4:** Run `pnpm --filter notify-client test && pnpm --filter notify-client build`. Expect PASS, with `dist/notify.js` present and the gzipped size reported ≤ 8 KB.
- [ ] **Step 5:** Commit `feat(notify-client): SSE toasts and activity beats`.

---

### Task 11: Lab UI (functional)

**Files:**
- Create: `apps/lab/` (Vite react-ts, `base: "/lab/"`, react-router), `src/api.ts`, `src/copy.ts`, `src/routes/{Catalog,Interstitial,Admin}.tsx`, `src/useStatus.ts`, tests beside the components. Post-build: copy `packages/notify-client/dist/notify.js` to `apps/lab/dist/notify.js`.

**Interfaces:**
- Consumes: `/api/projects`, `/api/status`, `/api/start`, `/api/stop`, `/api/email`, `/api/events`, `/api/admin/*`.
- Produces routes:
  - `/lab/` (Catalog): project cards (name, tagline, ETA, demo link), a box status panel (what's running, holder alias or "you", window/grace countdown), the queue list with `(Me)`, and a "Run live" button per card. A short "How this works" section explains: one project at a time (2 CPUs), why the socket is isolated, and "started ≠ ready".
  - `/lab/p/:id` (Interstitial). States, from `/api/status` and refreshed on any SSE message: **none** (Start button + ETA + demo link), **starting** (progress against `expected_boot_s`, why it takes time), **queued** (position, alias, estimate = position × 15 min upper bound, optional email field explaining its only use), **in use by others**, **failed** (error copy + demo link). When the viewer is holder and status is `ready`, it navigates to `/p/:id/`.
  - `/lab/admin`: secret form, then overview, force-stop and clear-queue.
  - `useStatus()` refetches status on every SSE message plus every 10s fallback.
  - All copy lives in `src/copy.ts`.

- [ ] **Step 1: Write failing tests** (vitest + Testing Library, `fetch` mocked): `interstitial_none_shows_start_eta_and_demo`, `interstitial_queued_shows_position_and_optional_email`, `interstitial_redirects_holder_when_ready` (asserts `window.location.assign("/p/a/")`), `interstitial_failed_shows_demo_link`, `catalog_marks_me_in_queue`.
- [ ] **Step 2:** Run `pnpm --filter lab test` and expect FAIL.
- [ ] **Step 3:** Implement the routes, hooks and copy. Keep styling minimal and token-based (CSS variables) so the design-system pass can replace it.
- [ ] **Step 4:** Run `pnpm --filter lab test && pnpm --filter lab build && pnpm --filter lab lint` and expect PASS.
- [ ] **Step 5:** Commit `feat(lab): catalog, interstitial, and admin UI`.

---

### Task 12: nginx, compose, example projects, end-to-end test, onboarding doc

**Files:**
- Create: `infra/proxy/nginx.conf`, `infra/proxy/snippets/project-proxy.conf`, `infra/proxy/Dockerfile` (multi-stage: `node:24-slim` builds `apps/lab` + notify-client, then `nginx:alpine` serves `/usr/share/nginx/html/lab`). Replace `infra/proxy/README.md`.
- Modify: root `docker-compose.yml`: replace the `landing` service with `proxy`, drop the published control-plane port, and add the networks/volumes below.
- Create: `projects/_examples/{fast,slow}/{stack.toml,docker-compose.yml,app.py}`. `app.py` is a stdlib HTTP server serving `/p/<id>/` (an HTML page with `</body>`) and `/p/<id>/healthz` (503 until `READY_AFTER_S` seconds after start, then 200). fast=`2`, slow=`20` (`expected_boot_s` likewise, `timeout_s` 10 for fast and 60 for slow).
- Create: `tests/integration/test_e2e.py`, `docs/adding-a-project.md`
- Modify: `Makefile` (add `render`, `prepare`, `e2e`, and make `up` create the external `orch-stacks` network)
- Modify: `README.md`

**Interfaces:**
- `nginx.conf`: `resolver 127.0.0.11 valid=10s`. `location /lab/` uses `try_files $uri /lab/index.html`. `location /api/` proxies to `control-plane:8000` with buffering off and read timeout 1h (for SSE), and sets `X-Real-IP`. `location /internal/ { return 404; }` and `location /agent/ { return 404; }`. `include /etc/nginx/generated/*.conf`.
- `project-proxy.conf`: `proxy_set_header Accept-Encoding ""`, `sub_filter '</body>' '<script src="/lab/notify.js" defer></script></body>'`, `sub_filter_once on`, `sub_filter_types text/html`, websocket upgrade headers, `proxy_set_header Host $host`, and `X-Real-IP`.
- `docker-compose.yml`: networks `orch-internal` (internal) and `orch-stacks` (external, created by `make up`). `nginx` (ports 80/443, on `orch-internal` + `orch-stacks`), `control-plane` (`orch-internal`, volume `orch-data:/data`), `agent` (`orch-internal` + `orch-stacks`, mounts `/var/run/docker.sock`, `./projects` and `${ORCH_REPOS_DIR:-/srv/orch/repos}` **at identical host paths** (so relative bind mounts inside project composes resolve on the host daemon), **no ports**). Each example project's entry service joins `orch-stacks` with alias `<id>-entry`.
- `docs/adding-a-project.md`: the §7 contract as a checklist, the manifest reference, the sub-path gotchas (Vite `base`, FastAPI `root_path`, websockets), and the steps `orchctl validate` → `make render prepare up`.

- [ ] **Step 1: Write the failing e2e test** (`@pytest.mark.integration`; brings the stack up with `ORCH_INCLUDE_HIDDEN=1` and `ORCH_LEASE__WINDOW_S=5 ORCH_LEASE__GRACE_S=3 ORCH_LEASE__IDLE_S=3`; two httpx clients with separate cookie jars against `http://localhost`):
  - `test_gate_redirects_before_ready`: `GET /p/fast/` returns 302 to `/lab/p/fast`.
  - `test_holder_reaches_stack_with_injected_script`: A starts `fast`, status polls to `ready` within 15s, then `GET /p/fast/` returns 200 with a body containing `/lab/notify.js`, while B's `GET /p/fast/` returns 302.
  - `test_handoff_to_queued_visitor`: B starts `slow` and is queued. Within window + grace + 25s, B is holder with `ready`, `docker compose ls` no longer lists `orch-fast`, and A's `/p/fast/` gives 302.
  - `test_boot_timeout_fails_and_releases`: a temp manifest with `READY_AFTER_S=999`, `timeout_s=5`. Status becomes `failed`, then the lease is released.
  - `test_internal_paths_not_public`: `/internal/gate/fast` and `/agent/desired` return 404 through nginx.
- [ ] **Step 2:** Run `make e2e` (`make render prepare up && uv run pytest -m integration tests/integration -v; make down`) and expect FAIL.
- [ ] **Step 3:** Implement the configs, example projects, compose file and Makefile, and write the onboarding doc and the README quickstart.
- [ ] **Step 4:** Run `make e2e` and expect all five to PASS. Then run `uv run pytest -m "not integration"` and `pnpm -r test` and expect PASS.
- [ ] **Step 5:** Commit `feat(infra): nginx gateway, compose, example projects, e2e`.

---

## Self-review notes

- Spec coverage: §5 components (Tasks 5–12), §6 rules (Tasks 3–4, single-user gate in 6), §6 events/email/admin (5–6), §7 contract + prepare + examples (2, 8, 9, 12), §10 tests (each task plus 12). TLS and deploy on the Oracle box are left to the builder per spec §11. They're not planned here.
- Deferred by spec: visual design pass (design-system workstream), sharing mode, onboarding real projects.
