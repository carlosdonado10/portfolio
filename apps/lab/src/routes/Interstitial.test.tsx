import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { TURN_MIN, HANDOFF_MIN } from "../copy"
import { FakeEventSource, installApi, PROJECTS, renderAt, statusBody } from "../test-utils"

const base = { "GET /api/projects": { body: PROJECTS } }

describe("Interstitial", () => {
  it("interstitial_none_shows_start_eta_and_demo", async () => {
    installApi({ ...base, "GET /api/status": { body: statusBody() } })
    renderAt("/p/a")
    expect(await screen.findByRole("button", { name: /run alpha rag live/i })).toBeInTheDocument()
    expect(screen.getByText(/about 60 seconds/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /demo/i })).toHaveAttribute(
      "href",
      "https://demo.example/a",
    )
  })

  it("interstitial_queued_shows_position_and_optional_email", async () => {
    installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({
          active: "b",
          status: "ready",
          holder_alias: "Quiet Otter",
          queue: [{ alias: "Brave Heron", stack_id: "a", me: true }],
          me: { role: "queued", position: 1, alias: "Brave Heron" },
        }),
      },
    })
    renderAt("/p/a")
    expect(await screen.findByText(/position 1/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Brave Heron/).length).toBeGreaterThan(0)
    const email = screen.getByLabelText(/email/i)
    expect(email).not.toBeRequired()
    expect(screen.getByText(/only used to/i)).toBeInTheDocument()
  })

  it("queue_estimate_uses_turn_and_handoff_constants", async () => {
    installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({
          active: "b",
          status: "ready",
          queue: [
            { alias: "x", stack_id: "b", me: false },
            { alias: "y", stack_id: "a", me: true },
          ],
          me: { role: "queued", position: 2, alias: "y" },
        }),
      },
    })
    renderAt("/p/a")
    expect(await screen.findByText(`up to ~${2 * (TURN_MIN + HANDOFF_MIN)} min`, { exact: false })).toBeInTheDocument()
    expect(TURN_MIN + HANDOFF_MIN).toBe(18)
  })

  it("interstitial_redirects_holder_when_ready", async () => {
    const assign = vi.fn()
    vi.stubGlobal("location", { ...window.location, assign })
    installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({
          active: "a",
          status: "ready",
          holder_alias: "Me",
          me: { role: "holder", position: null, alias: "Me" },
        }),
      },
    })
    renderAt("/p/a")
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/p/a/"))
    expect(assign).toHaveBeenCalledTimes(1)
  })

  it("interstitial_failed_shows_demo_link", async () => {
    installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({
          active: "a",
          status: "failed",
          holder_alias: "Me",
          me: { role: "holder", position: null, alias: "Me" },
        }),
      },
    })
    renderAt("/p/a")
    expect((await screen.findAllByText(/health check/i)).length).toBeGreaterThan(0)
    expect(screen.getByRole("link", { name: /demo/i })).toHaveAttribute(
      "href",
      "https://demo.example/a",
    )
  })

  it("interstitial_switch_offered_to_holder_of_other_project", async () => {
    const user = userEvent.setup()
    const spy = installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({
          active: "b",
          status: "ready",
          holder_alias: "Me",
          me: { role: "holder", position: null, alias: "Me" },
        }),
      },
      "POST /api/start": { body: statusBody() },
    })
    renderAt("/p/a")
    expect(await screen.findByText(/you're running Beta Vision/i)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /switch to alpha rag/i }))
    const post = spy.mock.calls.find(([, init]) => init?.method === "POST")
    expect(post?.[0]).toBe("/api/start")
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ stack_id: "a" })
  })

  it("start_error_detail_is_shown_verbatim", async () => {
    const user = userEvent.setup()
    installApi({
      ...base,
      "GET /api/status": { body: statusBody() },
      "POST /api/start": { status: 429, body: { detail: "Too many requests, because reasons." } },
    })
    renderAt("/p/a")
    await user.click(await screen.findByRole("button", { name: /run alpha rag live/i }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests, because reasons.")
  })

  it("interstitial_starting_shows_capped_progress", async () => {
    installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({
          active: "a",
          status: "starting",
          holder_alias: "Me",
          me: { role: "holder", position: null, alias: "Me" },
        }),
      },
    })
    renderAt("/p/a")
    const bar = await screen.findByRole("progressbar")
    expect(Number(bar.getAttribute("aria-valuenow"))).toBeLessThanOrEqual(95)
    expect(screen.getByText(/started isn't ready/i)).toBeInTheDocument()
  })
})

describe("Interstitial resilience", () => {
  it("projects_load_failure_retries_and_recovers", async () => {
    let calls = 0
    installApi({
      "GET /api/projects": () => (calls++ === 0 ? { status: 500, body: {} } : { body: PROJECTS }),
      "GET /api/status": { body: statusBody() },
    })
    renderAt("/p/a")
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't load the project list/i)
    expect(screen.getByRole("button", { name: /retry now/i })).toBeInTheDocument()
    FakeEventSource.instances[0]?.emit({ type: "queue_changed" })
    expect(await screen.findByRole("button", { name: /run alpha rag live/i })).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("countdown_is_not_in_a_live_region", async () => {
    installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({
          active: "b",
          status: "ready",
          holder_alias: "Quiet Otter",
          window_ends_at: Date.now() / 1000 + 600,
        }),
      },
    })
    renderAt("/p/a")
    const timers = await screen.findAllByRole("timer")
    for (const t of timers) expect(t.closest("[aria-live]")).toBeNull()
  })
})

describe("Interstitial projects retries", () => {
  it("projects_load_is_not_duplicated_while_in_flight", async () => {
    const spy = installApi({ "GET /api/status": { body: statusBody() } })
    const never = new Promise<Response>(() => {})
    const inner = spy.getMockImplementation()
    spy.mockImplementation((input, init) =>
      String(input) === "/api/projects" ? never : (inner?.(input, init) ?? never),
    )
    renderAt("/p/a")
    await screen.findByText(/loading/i)
    for (let i = 0; i < 3; i++) {
      FakeEventSource.instances[0]?.emit({ type: "queue_changed" })
      await Promise.resolve()
    }
    await waitFor(() => expect(spy.mock.calls.filter(([u]) => u === "/api/status").length).toBeGreaterThan(2))
    expect(spy.mock.calls.filter(([u]) => u === "/api/projects")).toHaveLength(1)
  })

  it("projects_retry_button_recovers", async () => {
    const user = userEvent.setup()
    let calls = 0
    installApi({
      "GET /api/projects": () => (calls++ === 0 ? { status: 500, body: {} } : { body: PROJECTS }),
      "GET /api/status": { body: statusBody() },
    })
    renderAt("/p/a")
    await user.click(await screen.findByRole("button", { name: /retry now/i }))
    expect(await screen.findByRole("button", { name: /run alpha rag live/i })).toBeInTheDocument()
  })
})
