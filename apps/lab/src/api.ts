export interface Project {
  id: string
  name: string
  tagline: string
  base_path: string
  expected_boot_s: number
  demo_url: string
}

interface QueueEntry {
  alias: string
  stack_id: string
  me: boolean
}

export interface StatusBody {
  active: string | null
  status: "stopped" | "starting" | "ready" | "failed"
  holder_alias: string | null
  window_ends_at: number | null
  grace_deadline: number | null
  queue: QueueEntry[]
  me: { role: "holder" | "queued" | "none"; position: number | null; alias: string | null }
}

export interface AdminOverview {
  state: unknown
  sessions: { sid: string; email: string | null; ip: string | null; created_at: number }[]
  recent_visits: { sid: string; at: number; path?: string }[]
}

/** An HTTP error whose `detail` is human copy from the control plane, shown verbatim. */
export class ApiError extends Error {
  readonly status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = ""
    try {
      const data = (await res.json()) as { detail?: unknown }
      if (typeof data.detail === "string") detail = data.detail
    } catch {
      // non-JSON error body: fall through to the generic message
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  projects: () => request<Project[]>("GET", "/api/projects"),
  status: () => request<StatusBody>("GET", "/api/status"),
  start: (stackId: string) => request<StatusBody>("POST", "/api/start", { stack_id: stackId }),
  stop: () => request<StatusBody>("POST", "/api/stop"),
  email: (email: string) => request<undefined>("POST", "/api/email", { email }),
  adminLogin: (secret: string) => request<{ ok: boolean }>("POST", "/api/admin/login", { secret }),
  adminForceStop: () => request<StatusBody>("POST", "/api/admin/force-stop"),
  adminClearQueue: () => request<StatusBody>("POST", "/api/admin/clear-queue"),
  adminOverview: () => request<AdminOverview>("GET", "/api/admin/overview"),
}
