# @portfolio/notify-client

A tiny, dependency-free script that nginx injects into every project page
served at `/p/<id>/` (`sub_filter` before `</body>` adds
`<script src="/lab/notify.js" defer>`). It tells the visitor about their turn
and sends activity beats so an idle holder can be detected. It is served from
the same origin as the API.

## Behaviour

- Appends one `<orch-notify>` host (open shadow root, scoped styles) to
  `document.body`; a second injection is a no-op.
- Opens `EventSource("/api/events")` and renders toasts bottom-right. All text
  is set with `textContent`; `demo_url` becomes a link only if it is `http(s):`.
  Toasts auto-dismiss after 8 s, except `grace_started` and `evicted`, which
  persist and use `role="alert"`. `grace_started` shows an `m:ss` countdown to
  `deadline` and a link to `/lab/`.
- Sends `POST /api/activity` (same-origin cookie, `keepalive`) on
  `mousemove`, `keydown`, `click`, `focus` and `visibilitychange` (visible),
  throttled to one beat per 30 s with the first sent immediately. Failures are
  ignored.

## Message contract

Each SSE message is `data: <json>`:
`{"type", "stack_id": str|null, "title", "body", ...extra}`.
Types: `queue_changed` (broadcast refetch ping, never toasted), `your_turn`,
`stack_starting`, `stack_ready`, `grace_started` (`deadline`, epoch seconds),
`grace_cancelled`, `evicted`, `stack_failed` (`error`, `demo_url`).
`: ping` comments arrive every 15 s.

## Build

```
pnpm --filter @portfolio/notify-client build      # dist/notify.js (IIFE, minified)
pnpm --filter @portfolio/notify-client size       # fails if gzip > 8 KB
pnpm --filter @portfolio/notify-client test       # vitest + jsdom
pnpm --filter @portfolio/notify-client typecheck
```
