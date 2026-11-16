import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

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

  it("queue_estimate_uses_lease_durations_from_status", async () => {
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
          lease: { window_s: 600, grace_s: 120, idle_s: 60 },
        }),
      },
    })
    renderAt("/p/a")
    // 2 * (10 + 2) minutes, from the server's configuration, not constants.
    expect(await screen.findByText("up to ~24 min", { exact: false })).toBeInTheDocument()
    expect(screen.getByText(/each turn is 10 minutes plus a 2-minute handoff/i)).toBeInTheDocument()
  })

  it("leave_queue_posts_leave_not_stop", async () => {
    const user = userEvent.setup()
    const spy = installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({
          active: "b",
          status: "ready",
          queue: [{ alias: "y", stack_id: "a", me: true }],
          me: { role: "queued", position: 1, alias: "y" },
        }),
      },
      "POST /api/leave": { status: 204, body: null },
    })
    renderAt("/p/a")
    await user.click(await screen.findByRole("button", { name: /leave the queue/i }))
    const posts = spy.mock.calls.filter(([, init]) => init?.method === "POST").map(([u]) => u)
    expect(posts).toEqual(["/api/leave"])
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("busy_copy_names_the_running_project_and_idle_rule", async () => {
    installApi({
      ...base,
      "GET /api/status": {
        body: statusBody({ active: "b", status: "ready", holder_alias: "Quiet Otter" }),
      },
    })
    renderAt("/p/a")
    expect(
      await screen.findByText(/Beta Vision is running for Quiet Otter\. The box runs one stack/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/or another project/)).not.toBeInTheDocument()
    expect(screen.getByText(/stops interacting for about 3 minutes/i)).toBeInTheDocument()
  })

  it("demo_link_hidden_without_a_web_url", async () => {
    installApi({
      "GET /api/projects": {
        body: [
          { ...PROJECTS[0], demo_url: null },
          { ...PROJECTS[1], demo_url: "javascript:alert(1)" },
        ],
      },
      "GET /api/status": { body: statusBody() },
    })
    const { unmount } = renderAt("/p/a")
    expect(await screen.findByRole("button", { name: /run alpha rag live/i })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /demo/i })).not.toBeInTheDocument()
    unmount()
    renderAt("/p/b")
    expect(await screen.findByRole("button", { name: /run beta vision live/i })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /demo/i })).not.toBeInTheDocument()
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
