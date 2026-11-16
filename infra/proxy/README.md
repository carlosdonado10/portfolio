# infra/proxy

The nginx gateway. It is the only service that publishes a host port
(`${HTTP_PORT:-8080}` -> container `:80`) and it serves the built lab UI.

| Path | Goes to |
| --- | --- |
| `/` | 302 to `/lab/` |
| `/lab/` | static lab UI (built into the image), SPA fallback to `/lab/index.html` |
| `/lab/notify.js` | the notify-client bundle injected into project pages |
| `/api/` | control-plane `:8000` (SSE on `/api/events`: no buffering, 1h read timeout) |
| `/p/<id>/` | the project stack's entry service, behind a per-request gate |
| `/internal/`, `/agent/` | 404. These exist on the control-plane but are never public |

## Files

- `Dockerfile`: multi-stage. `node:24-slim` (pnpm via Corepack, version from the root
  `package.json`) builds `@portfolio/lab`; `nginx:1.27-alpine` serves it. Build context is
  the repo root: `docker build -f infra/proxy/Dockerfile .`
- `nginx.conf`: the whole server. Docker DNS `resolver 127.0.0.11 valid=10s ipv6=off;`,
  `X-Real-IP $remote_addr` on every proxied location (it overwrites any client-sent value;
  the control-plane rate-limits on it), and `include /etc/nginx/generated/*.conf;`.
- `snippets/project-proxy.conf`: shared by every project location. Websocket headers,
  `Accept-Encoding ""`, and the `sub_filter` that injects
  `<script src="/lab/notify.js" defer></script>` before `</body>` in HTML responses.
- `snippets/security-headers.conf`: `nosniff` and `Referrer-Policy: same-origin` for the lab
  and API. There is deliberately no CSP, so project stacks keep working.
- `generated/`: output of `make render` (`orchctl render-nginx`). `*.conf` is gitignored;
  the directory is bind-mounted read-only into the container at `/etc/nginx/generated/`.

## How a project request flows

`location /p/<id>/` runs `auth_request /_gate/<id>`, an internal location that calls the
control-plane's `/internal/gate/<id>` with the visitor's cookie. `204` means "this session
holds the lease and the stack is ready", and nginx proxies to `http://<id>-entry:<port>`
(resolved per request on the `orch-stacks` network). Anything else (`401`) redirects to
`/lab/p/<id>`, the interstitial.

## Operating it

```bash
make render                                # rewrite generated/projects.conf from manifests
docker compose exec proxy nginx -t         # check the config
docker compose exec proxy nginx -s reload  # pick up new routes without a restart
```

The control-plane gate upstream is resolved when nginx starts, so the proxy waits for the
control-plane healthcheck in `docker-compose.yml`. If you recreate the control-plane alone,
run `docker compose restart proxy`.

## TLS

Not handled here. Terminate TLS in front of this container (the box's own Caddy/nginx, or a
Cloudflare tunnel) and set `ORCH_COOKIE_SECURE=true`.
