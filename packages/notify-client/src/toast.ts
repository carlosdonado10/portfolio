export interface NotifyMessage {
  type: string
  stack_id?: string | null
  title: string
  body: string
  deadline?: number
  error?: string
  demo_url?: string
  [key: string]: unknown
}

const STYLE = `
:host { all: initial; }
.stack { position: fixed; right: 16px; bottom: 16px; z-index: 2147483647; display: flex; flex-direction: column; gap: 8px; max-width: min(360px, calc(100vw - 32px)); font: 14px/1.4 system-ui, sans-serif; }
.toast { position: relative; padding: 12px 36px 12px 14px; border-radius: 10px; background: #1f1d1a; color: #f5f1ea; box-shadow: 0 6px 24px rgba(0,0,0,.3); animation: in .2s ease-out; }
.toast.warn { border-left: 4px solid #d97757; }
.title { font-weight: 600; margin: 0 0 2px; }
.body { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.countdown { font-variant-numeric: tabular-nums; font-weight: 600; margin: 4px 0 0; }
a { color: #f0b89f; display: inline-block; margin-top: 6px; margin-right: 12px; }
button { position: absolute; top: 6px; right: 6px; width: 24px; height: 24px; border: 0; border-radius: 6px; background: transparent; color: inherit; font-size: 18px; line-height: 1; cursor: pointer; }
button:hover { background: rgba(255,255,255,.15); }
button:focus-visible, a:focus-visible { outline: 2px solid #f0b89f; outline-offset: 2px; }
@keyframes in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .toast { animation: none; } }
`

const dismissers = new WeakMap<HTMLElement, () => void>()
const SUPERSEDES_GRACE = new Set(["grace_cancelled", "your_turn", "stack_ready", "evicted", "stack_failed"])

export const PERSISTENT = new Set(["grace_started", "evicted"])
const AUTO_DISMISS_MS = 8000

function ensureStack(root: ShadowRoot): HTMLElement {
  let stack = root.querySelector<HTMLElement>(".stack")
  if (!stack) {
    const style = document.createElement("style")
    style.textContent = STYLE
    stack = document.createElement("div")
    stack.className = "stack"
    root.append(style, stack)
  }
  return stack
}

function link(href: string, text: string): HTMLAnchorElement {
  const a = document.createElement("a")
  a.href = href
  a.textContent = text
  return a
}

function isHttpUrl(value: unknown): value is string {
  if (typeof value !== "string") return false
  try {
    const u = new URL(value)
    return u.protocol === "http:" || u.protocol === "https:"
  } catch {
    return false
  }
}

function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

/** Renders one toast. All server text goes through textContent, never HTML parsing. */
export function renderToast(root: ShadowRoot, msg: NotifyMessage): HTMLElement {
  const stack = ensureStack(root)
  const persistent = PERSISTENT.has(msg.type)

  const el = document.createElement("div")
  el.className = persistent ? "toast warn" : "toast"
  el.setAttribute("role", persistent ? "alert" : "status")
  el.dataset.type = msg.type

  const title = document.createElement("p")
  title.className = "title"
  title.textContent = msg.title
  const body = document.createElement("p")
  body.className = "body"
  body.textContent = msg.body
  el.append(title, body)

  let timer: ReturnType<typeof setInterval> | undefined
  if (msg.type === "grace_started" && typeof msg.deadline === "number") {
    const deadline = msg.deadline
    const cd = document.createElement("p")
    cd.className = "countdown"
    const tick = () => {
      const left = deadline - Date.now() / 1000
      cd.textContent = formatCountdown(left)
      if (left <= 0 && timer !== undefined) clearInterval(timer)
    }
    timer = setInterval(tick, 1000)
    tick()
    el.append(cd)
  }
  if (msg.type === "grace_started") el.append(link("/lab/", "Back to the lab"))
  if (isHttpUrl(msg.demo_url)) el.append(link(msg.demo_url, "Open demo"))

  const close = document.createElement("button")
  close.type = "button"
  close.setAttribute("aria-label", "Dismiss notification")
  close.textContent = "×"
  let autoTimer: ReturnType<typeof setTimeout> | undefined
  const dismiss = () => {
    if (timer !== undefined) clearInterval(timer)
    if (autoTimer !== undefined) clearTimeout(autoTimer)
    el.remove()
  }
  close.addEventListener("click", dismiss)
  el.append(close)
  dismissers.set(el, dismiss)

  if (!persistent) autoTimer = setTimeout(dismiss, AUTO_DISMISS_MS)

  // Persistent toasts replace each other (a new grace/eviction supersedes the old).
  const stale: string[] = []
  if (persistent) stale.push(".toast.warn")
  if (SUPERSEDES_GRACE.has(msg.type)) stale.push('.toast[data-type="grace_started"]')
  if (stale.length) {
    stack.querySelectorAll<HTMLElement>(stale.join(",")).forEach((t) => dismissers.get(t)?.())
  }
  stack.append(el)
  return el
}
