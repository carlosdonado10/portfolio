import { render } from "@testing-library/react"
import { vi } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router"

import type { Project, StatusBody } from "./api"
import Interstitial from "./routes/Interstitial"
import Catalog from "./routes/Catalog"

export const PROJECTS: Project[] = [
  {
    id: "a",
    name: "Alpha RAG",
    tagline: "Retrieval over papers",
    base_path: "/p/a/",
    expected_boot_s: 60,
    demo_url: "https://demo.example/a",
  },
  {
    id: "b",
    name: "Beta Vision",
    tagline: "Image classifier",
    base_path: "/p/b/",
    expected_boot_s: 90,
    demo_url: "https://demo.example/b",
  },
]

export function statusBody(over: Partial<StatusBody> = {}): StatusBody {
  return {
    active: null,
    status: "stopped",
    holder_alias: null,
    window_ends_at: null,
    grace_deadline: null,
    queue: [],
    me: { role: "none", position: null, alias: null },
    lease: { window_s: 900, grace_s: 180, idle_s: 180 },
    ...over,
  }
}

export class FakeEventSource {
  static instances: FakeEventSource[] = []
  onmessage: ((e: MessageEvent<string>) => void) | null = null
  closed = false
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }
  close() {
    this.closed = true
  }
  emit(data: object) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }))
  }
}

type Reply = { status?: number; body: unknown }
export type Routes = Record<string, Reply | (() => Reply)>

/** Stubs fetch + EventSource. Keys are "METHOD /path". Returns the fetch spy. */
export function installApi(routes: Routes) {
  FakeEventSource.instances = []
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(input)}`
    const entry = routes[key]
    if (!entry) return Promise.resolve(new Response("not mocked: " + key, { status: 500 }))
    const reply = typeof entry === "function" ? entry() : entry
    return Promise.resolve(
      new Response(reply.status === 204 ? null : JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { "content-type": "application/json" },
      }),
    )
  })
  vi.stubGlobal("fetch", spy)
  vi.stubGlobal("EventSource", FakeEventSource)
  return spy
}

export function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<Catalog />} />
        <Route path="/p/:id" element={<Interstitial />} />
      </Routes>
    </MemoryRouter>,
  )
}
