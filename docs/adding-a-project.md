# Adding a project

A project is a docker-compose stack that lives in its own repo. This repo only holds a
manifest for it: `projects/<id>/stack.toml`. The orchestrator runs one stack at a time and
serves it at `/p/<id>/`. Background: spec section 7
(`docs/superpowers/specs/2026-11-15-orchestrator-design.md`). Working templates:
`projects/_examples/fast` and `projects/_examples/slow`.

## Checklist: what the project must provide

- [ ] **Runs under a sub-path.** It is served at `/p/<id>/`. nginx strips nothing and sends
      `X-Forwarded-Prefix: /p/<id>`. No hard-coded `/api`, `/static` or `/assets`.
- [ ] **Health endpoint** (relative to the entry, default `/healthz`) that returns 200 only
      when the app can really serve a user: models loaded, DB migrated. It is probed at
      `http://<id>-entry:<port>/p/<id><health.path>`, so it must also live under the
      sub-path.
- [ ] **Entry service joins the external network `orch-stacks`** with the alias
      `<id>-entry`. The compose publishes **no host ports**.
- [ ] **Images are built ahead of time.** The agent runs
      `compose up --no-build --pull never`, so every image must already exist locally.
      Give built services an explicit `image:` name. `orchctl prepare` does the build.
- [ ] **Stateless or self-contained volumes.** `compose down` (no `-v`) must be safe at any
      time. Relative bind mounts are fine; the agent mounts repos at their host paths.
- [ ] **HTML pages end with `</body>`** if you want the notify-client (toasts, activity
      beats) injected automatically. Otherwise include `/lab/notify.js` yourself or go
      without notifications.
- [ ] Boots within `health.timeout_s`, or it is marked `failed` and the lease is released.

Compose template for the entry service:

```yaml
services:
  web:
    build: .
    image: my-project-web:local
    networks:
      orch-stacks:
        aliases: [my-project-entry]   # <id>-entry
networks:
  orch-stacks:
    external: true
```

## Manifest reference

```toml
# projects/<id>/stack.toml   (the folder name must equal the id)
id = "rag-pipeline"             # lowercase alphanumerics and hyphens, max 40; becomes /p/rag-pipeline/
name = "RAG Pipeline"
tagline = "Retrieval-augmented QA over ..."
repo = "https://github.com/<owner>/rag-pipeline.git"   # optional; omit for in-repo examples
ref = "v1.2.0"                  # tag, branch or sha; default "main"
compose = "docker-compose.yml"  # relative to the repo root (or this folder if no repo)
entry = { service = "web", port = 8000 }          # what nginx proxies /p/<id>/ to
health = { path = "/healthz", timeout_s = 180, interval_s = 3 }
expected_boot_s = 90            # ETA shown on the interstitial
demo_url = "https://..."        # optional recorded walkthrough, always available
order = 100                     # catalog ordering (lower first); default 100
```

Unknown keys are rejected. A folder whose name starts with `_` is hidden from the public
catalog unless `ORCH_INCLUDE_HIDDEN=1`.

## Sub-path gotchas

- **Vite / React:** set `base: "/p/<id>/"` in `vite.config`, and use `import.meta.env.BASE_URL`
  for fetches to your own assets. For a router, set its `basename` to the same value.
- **FastAPI:** `FastAPI(root_path="/p/<id>")` (or run uvicorn with
  `--root-path /p/<id>`). nginx does not strip the prefix, so also mount your routes under
  it, or read `X-Forwarded-Prefix` and use `--proxy-headers`.
- **Other servers:** configure the app's base URL / script name the same way. Emit relative
  links, or links that start with `/p/<id>/`.
- **Websockets:** the gateway forwards `Upgrade`/`Connection` and keeps connections open for
  an hour. Connect to a path under `/p/<id>/` (for example `new WebSocket(location.pathname
  + "ws")`), never to `/ws`.
- **Cookies:** scope them to `Path=/p/<id>/` so projects do not see each other's.
- **Redirects:** never redirect to an absolute path outside `/p/<id>/`.

## Steps

1. Create `projects/<id>/stack.toml` (and a compose file in that folder if there is no
   `repo`).
2. Validate: `uv run orchctl validate` (add `--include-hidden` for `_` folders).
3. Render routes, build images, bring the platform up:

   ```bash
   make render prepare up
   ```

   `make render` writes `infra/proxy/generated/projects.conf`. `make prepare` clones or
   fetches each `repo` at `ref` into `$ORCH_REPOS_DIR/<id>` and builds the images. If the
   platform is already running, reload the gateway after rendering:
   `docker compose exec proxy nginx -s reload`, and restart the control-plane
   (`docker compose restart control-plane agent`) so they pick up the new manifest.
4. Open `http://localhost:8080/lab/`, start the project, and check that it reaches
   `ready` and renders under `/p/<id>/`.

Run `make e2e` to exercise the full flow against the example projects (needs Docker).
