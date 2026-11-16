import { createBeatSender } from "./beats"
import { renderToast, type NotifyMessage } from "./toast"

const HOST_TAG = "orch-notify"

function postBeat(): void {
  try {
    fetch("/api/activity", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
    }).catch(() => {})
  } catch {
    // ignore: beats are best-effort
  }
}

/** Initializes once per page; returns a teardown (used by tests). */
export function start(): () => void {
  if (document.querySelector(HOST_TAG)) return () => {}
  const ac = new AbortController()
  const host = document.createElement(HOST_TAG)
  const root = host.attachShadow({ mode: "open" })
  document.body.append(host)

  const beats = createBeatSender(postBeat)
  const onActivity = () => beats.onActivity()
  for (const ev of ["mousemove", "keydown", "click", "focus"]) {
    window.addEventListener(ev, onActivity, { passive: true, signal: ac.signal })
  }
  document.addEventListener(
    "visibilitychange",
    () => {
      if (document.visibilityState === "visible") beats.onActivity()
    },
    { passive: true, signal: ac.signal },
  )

  const teardown = () => {
    ac.abort()
    host.remove()
  }
  if (typeof EventSource === "undefined") return teardown
  const source = new EventSource("/api/events")
  source.onmessage = (e: MessageEvent<string>) => {
    let msg: NotifyMessage
    try {
      msg = JSON.parse(e.data) as NotifyMessage
    } catch {
      return
    }
    if (!msg || typeof msg.type !== "string" || msg.type === "queue_changed") return
    renderToast(root, {
      ...msg,
      title: String(msg.title ?? ""),
      body: String(msg.body ?? ""),
    })
  }
  return teardown
}

if (import.meta.env.MODE !== "test") start()
