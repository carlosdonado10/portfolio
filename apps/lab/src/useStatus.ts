import { useCallback, useSyncExternalStore } from "react"

import { api, type Project, type StatusBody } from "./api"

/** A per-session push the status poll can't reconstruct (the state has moved on). */
export interface Notice {
  type: "stack_failed" | "evicted"
  title: string
  body: string
  stack_id: string | null
  demo_url: string | null
}

export interface StatusSnapshot {
  status: StatusBody | null
  projects: Project[] | null
  error: string | null
  projectsFailed: boolean
  notice: Notice | null
}

const POLL_MS = 10_000
const EMPTY: StatusSnapshot = {
  status: null,
  projects: null,
  error: null,
  projectsFailed: false,
  notice: null,
}
const NOTICE_TYPES = new Set(["stack_failed", "evicted"])

/**
 * One app-wide store: a single EventSource and a single poll timer, shared by
 * every subscriber. It starts with the first subscriber and stops with the last.
 */
let snapshot: StatusSnapshot = EMPTY
const listeners = new Set<() => void>()
let source: EventSource | null = null
let timer: ReturnType<typeof setInterval> | undefined
let generation = 0

function set(patch: Partial<StatusSnapshot>) {
  snapshot = { ...snapshot, ...patch }
  listeners.forEach((l) => l())
}

async function refresh(): Promise<void> {
  const gen = generation
  let ok = false
  try {
    const status = await api.status()
    ok = true
    if (gen === generation) set({ status, error: null })
  } catch (e) {
    if (gen === generation) set({ error: e instanceof Error ? e.message || "error" : "error" })
  }
  if (gen !== generation) return
  // Strictly after the status call: on a first visit that response mints the
  // session cookie, and concurrent cookieless requests would each mint another.
  if (snapshot.projects === null) void loadProjects()
  if (ok && source === null) openEvents()
}

let projectsInFlight: Promise<void> | null = null

function loadProjects(): Promise<void> {
  projectsInFlight ??= fetchProjects().finally(() => {
    projectsInFlight = null
  })
  return projectsInFlight
}

async function fetchProjects(): Promise<void> {
  const gen = generation
  try {
    const projects = await api.projects()
    if (gen === generation) set({ projects, projectsFailed: false })
  } catch {
    // retried by refresh() on every poll tick and SSE message while projects is null
    if (gen === generation) set({ projectsFailed: true })
  }
}

function asNotice(raw: string): Notice | null {
  let msg: unknown
  try {
    msg = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof msg !== "object" || msg === null) return null
  const m = msg as Record<string, unknown>
  if (typeof m.type !== "string" || !NOTICE_TYPES.has(m.type)) return null
  const str = (v: unknown) => (typeof v === "string" ? v : null)
  return {
    type: m.type as Notice["type"],
    title: str(m.title) ?? "",
    body: str(m.body) ?? "",
    stack_id: str(m.stack_id),
    demo_url: str(m.demo_url),
  }
}

/** Only opened once a status call has succeeded, so the session cookie exists. */
function openEvents() {
  if (typeof EventSource === "undefined") return
  source = new EventSource("/api/events")
  source.onmessage = (e: MessageEvent<string>) => {
    const notice = asNotice(e.data)
    if (notice) set({ notice })
    void refresh()
  }
}

function start() {
  generation++
  void refresh()
  timer = setInterval(() => void refresh(), POLL_MS)
}

function stop() {
  generation++
  projectsInFlight = null
  clearInterval(timer)
  timer = undefined
  source?.close()
  source = null
  snapshot = EMPTY
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  if (listeners.size === 1) start()
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) stop()
  }
}

function dismissNotice() {
  set({ notice: null })
}

export function useStatus(): StatusSnapshot & {
  refresh: () => Promise<void>
  dismissNotice: () => void
} {
  const snap = useSyncExternalStore(subscribe, () => snapshot)
  const stable = useCallback(() => refresh(), [])
  return { ...snap, refresh: stable, dismissNotice }
}
