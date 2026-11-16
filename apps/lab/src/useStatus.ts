import { useCallback, useSyncExternalStore } from "react"

import { api, type Project, type StatusBody } from "./api"

export interface StatusSnapshot {
  status: StatusBody | null
  projects: Project[] | null
  error: string | null
}

const POLL_MS = 10_000
const EMPTY: StatusSnapshot = { status: null, projects: null, error: null }

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
  try {
    const status = await api.status()
    if (gen === generation) set({ status, error: null })
  } catch (e) {
    if (gen === generation) set({ error: e instanceof Error ? e.message || "error" : "error" })
  }
}

async function loadProjects(): Promise<void> {
  const gen = generation
  try {
    const projects = await api.projects()
    if (gen === generation) set({ projects })
  } catch {
    // surfaced via the status error; the next subscriber start retries
  }
}

function start() {
  generation++
  void loadProjects()
  void refresh()
  timer = setInterval(() => void refresh(), POLL_MS)
  if (typeof EventSource !== "undefined") {
    source = new EventSource("/api/events")
    source.onmessage = () => void refresh()
  }
}

function stop() {
  generation++
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

export function useStatus(): StatusSnapshot & { refresh: () => Promise<void> } {
  const snap = useSyncExternalStore(subscribe, () => snapshot)
  const stable = useCallback(() => refresh(), [])
  return { ...snap, refresh: stable }
}
