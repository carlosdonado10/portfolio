# infra/proxy

The nginx gateway. It is the only service that publishes a host port
(`${HTTP_BIND:-0.0.0.0}:${HTTP_PORT:-8080}` -> container `:80`) and it serves the built lab UI.

| Path | Goes to |
| --- | --- |
| `/` | 302 to `/lab/` |
| `/lab/` | static lab UI (built into the image), SPA fallback to `/lab/index.html` |
| `/lab/notify.js` | the notify-client bundle injected into project pages |
| `/api/` | control-plane `:8000` (SSE on `/api/events`: no buffering, 1h read timeout) |
| `/p/<id>` | 301 to `/p/<id>/` |
| `/p/<id>/` | the project stack's entry service, behind a per-request gate |
| `/internal/`, `/agent/` | 404. These exist on the control-plane but are never public |

## Files

- `Dockerfile`: multi-stage. `node:24-slim` (pnpm via Corepack, version from the root
  `package.json`) builds `@portfolio/lab`; `nginx:1.27-alpine` serves it. Build context is
  the repo root: `docker build -f infra/proxy/Dockerfile .`
- `nginx.conf`: the whole server. Docker DNS `resolver 127.0.0.11 valid=2s ipv6=off;`,
  `X-Real-IP $remote_addr` on every proxied location (it overwrites any client-sent value;
  the control-plane rate-limits on it), the `$project_cookie` maps that strip `orch_*`
  cookies, a commented `set_real_ip_from` / `real_ip_header` block for a TLS front proxy,
  and `include /etc/nginx/generated/*.conf;`.
- `snippets/project-proxy.conf`: shared by every project location. Websocket headers,
  `Cookie $project_cookie` (the visitor's cookies without `orch_sid`/`orch_admin`, so
  project code never sees the orchestrator's session), `Accept-Encoding ""`, and the
  `sub_filter` that injects
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

The gate upstream is resolved per request, so recreating the control-plane needs no proxy
restart. If the control-plane is down, `/p/<id>/` degrades to the interstitial (redirect to
`/lab/p/<id>`).

## TLS and the real client IP

TLS is not handled here. Run a TLS front proxy on the host (Caddy, or the host's own nginx)
that forwards to this container:

1. **Bind to loopback.** Set `HTTP_BIND=127.0.0.1` in `.env` so the plain-http port is only
   reachable from the host's front proxy, not from the internet. The default `0.0.0.0` is for
   local use or when nothing sits in front.
2. **Trust the front proxy's client IP.** Behind a proxy, `$remote_addr` is the proxy, so every
   visitor would share one rate-limit bucket. Uncomment the `set_real_ip_from` /
   `real_ip_header X-Forwarded-For` block in `nginx.conf`, with `set_real_ip_from` set to the
   front proxy's address as this container sees it (the docker bridge gateway), and have the
   front proxy send `X-Forwarded-For`. Never trust `X-Forwarded-For` from arbitrary sources.
3. **Secure cookies need HTTPS.** `ORCH_COOKIE_SECURE=true` (the default) marks cookies
   `Secure`, so browsers only send them over HTTPS. Over plain http they are dropped and
   nobody can hold a place in line; set it to `false` only for local plain-http use.

```caddyfile
lab.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

## Cookies and project code

Projects share the lab's origin. nginx removes `orch_*` cookies from every request it proxies
to a project, and the admin cookie is scoped to `Path=/api/admin`. Project JavaScript can still
call `/api/*` same-origin, so sign out of the owner console before browsing projects (see
[ADR 0006](../../docs/decisions/0006-orchestrator-no-login-single-domain.md)).
