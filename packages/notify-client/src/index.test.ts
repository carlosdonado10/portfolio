import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createBeatSender } from "./beats"
import { start } from "./index"
import { renderToast } from "./toast"

function newRoot(): ShadowRoot {
  const host = document.createElement("div")
  document.body.append(host)
  return host.attachShadow({ mode: "open" })
}

class FakeES {
  static last: FakeES
  onmessage: ((e: MessageEvent<string>) => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeES.last = this
  }
  emit(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>)
  }
}

describe("beats", () => {
  it("beats_throttled_to_one_per_interval", () => {
    let t = 0
    const post = vi.fn()
    const s = createBeatSender(post, 30000, () => t)
    for (let i = 0; i < 100; i++) {
      t = i * 100
      s.onActivity()
    }
    expect(post).toHaveBeenCalledTimes(1)
    t = 40000
    s.onActivity()
    expect(post).toHaveBeenCalledTimes(2)
  })
})

describe("renderToast", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("toast_renders_title_and_body", () => {
    const el = renderToast(newRoot(), { type: "your_turn", title: "Your turn", body: "Go" })
    expect(el.textContent).toContain("Your turn")
    expect(el.textContent).toContain("Go")
    expect(el.getAttribute("role")).toBe("status")
  })

  it("grace_toast_shows_countdown_and_alert_role", () => {
    vi.setSystemTime(1_000_000)
    const deadline = 1_000 + 125
    const el = renderToast(newRoot(), { type: "grace_started", title: "t", body: "b", deadline })
    expect(el.getAttribute("role")).toBe("alert")
    expect(el.querySelector(".countdown")?.textContent).toBe("2:05")
    vi.advanceTimersByTime(5000)
    expect(el.querySelector(".countdown")?.textContent).toBe("2:00")
    vi.advanceTimersByTime(200_000)
    expect(el.querySelector(".countdown")?.textContent).toBe("0:00")
    expect(el.querySelector('a[href="/lab/"]')).not.toBeNull()
  })

  it("toast_text_is_not_parsed_as_html", () => {
    const el = renderToast(newRoot(), {
      type: "stack_failed",
      title: "x",
      body: "<img src=x onerror=alert(1)>",
    })
    expect(el.querySelector("img")).toBeNull()
    expect(el.textContent).toContain("<img src=x onerror=alert(1)>")
  })

  it("demo_link_only_for_http_urls", () => {
    const bad = renderToast(newRoot(), { type: "stack_failed", title: "x", body: "y", demo_url: "javascript:alert(1)" })
    expect(bad.querySelector("a")).toBeNull()
    const good = renderToast(newRoot(), { type: "stack_failed", title: "x", body: "y", demo_url: "https://demo.example/a" })
    expect(good.querySelector("a")?.getAttribute("href")).toBe("https://demo.example/a")
  })

  it("replacing_grace_toast_clears_its_interval", () => {
    vi.setSystemTime(1_000_000)
    const root = newRoot()
    renderToast(root, { type: "grace_started", title: "a", body: "b", deadline: 1_100 })
    const spy = vi.spyOn(globalThis, "clearInterval")
    renderToast(root, { type: "grace_started", title: "c", body: "d", deadline: 1_200 })
    expect(spy).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(1)
    expect(root.querySelectorAll(".toast")).toHaveLength(1)
  })

  it("grace_cancelled_dismisses_grace_toast", () => {
    vi.setSystemTime(1_000_000)
    const root = newRoot()
    const g = renderToast(root, { type: "grace_started", title: "a", body: "b", deadline: 1_100 })
    renderToast(root, { type: "grace_cancelled", title: "ok", body: "kept" })
    expect(g.isConnected).toBe(false)
    expect(root.querySelectorAll(".toast")).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(1) // only the new toast's auto-dismiss timeout
  })

  it("auto_dismisses_except_grace_and_evicted", () => {
    const root = newRoot()
    const a = renderToast(root, { type: "your_turn", title: "x", body: "y" })
    const b = renderToast(root, { type: "evicted", title: "x", body: "y" })
    vi.advanceTimersByTime(8001)
    expect(a.isConnected).toBe(false)
    expect(b.isConnected).toBe(true)
    b.querySelector("button")?.click()
    expect(b.isConnected).toBe(false)
  })
})

describe("start", () => {
  let teardown = () => {}
  beforeEach(() => {
    document.body.innerHTML = ""
    vi.stubGlobal("EventSource", FakeES)
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))))
  })
  afterEach(() => {
    teardown()
    vi.unstubAllGlobals()
  })

  it("queue_changed_is_not_toasted", () => {
    teardown = start()
    FakeES.last.emit({ type: "queue_changed", stack_id: null, title: "q", body: "q" })
    FakeES.last.emit({ type: "your_turn", stack_id: "a", title: "Hello", body: "b" })
    const root = (document.querySelector("orch-notify")?.shadowRoot as ShadowRoot)
    expect(root.querySelectorAll(".toast")).toHaveLength(1)
    expect(root.textContent).toContain("Hello")
  })

  it("does_not_initialize_twice", () => {
    teardown = start()
    start()
    expect(document.querySelectorAll("orch-notify")).toHaveLength(1)
    window.dispatchEvent(new Event("click"))
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith("/api/activity", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
    })
  })
})
