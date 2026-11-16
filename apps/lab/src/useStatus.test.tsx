import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { FakeEventSource, installApi, PROJECTS, statusBody } from "./test-utils"
import { useStatus } from "./useStatus"

function Probe({ id }: { id: string }) {
  const { status } = useStatus()
  return <p>{`${id}:${status?.status ?? "loading"}`}</p>
}

function NoticeProbe() {
  const { notice, dismissNotice } = useStatus()
  return notice ? (
    <button type="button" onClick={dismissNotice}>
      {`${notice.type}:${notice.title}`}
    </button>
  ) : (
    <p>no notice</p>
  )
}

describe("useStatus", () => {
  it("use_status_shares_one_event_source", async () => {
    let n = 0
    const spy = installApi({
      "GET /api/projects": { body: PROJECTS },
      "GET /api/status": () => ({ body: statusBody({ status: n++ === 0 ? "stopped" : "starting" }) }),
    })
    const { unmount } = render(
      <>
        <Probe id="one" />
        <Probe id="two" />
      </>,
    )
    await screen.findByText("one:stopped")
    expect(screen.getByText("two:stopped")).toBeInTheDocument()
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0]?.url).toBe("/api/events")
    FakeEventSource.instances[0]?.emit({ type: "queue_changed" })
    await waitFor(() => expect(screen.getByText("one:starting")).toBeInTheDocument())
    expect(spy.mock.calls.filter(([u]) => u === "/api/projects")).toHaveLength(1)
    unmount()
    expect(FakeEventSource.instances[0]?.closed).toBe(true)
  })

  it("event_source_opens_only_after_first_status_resolves", async () => {
    let release: (() => void) | undefined
    const spy = installApi({
      "GET /api/projects": { body: PROJECTS },
      "GET /api/status": { body: statusBody() },
    })
    const inner = spy.getMockImplementation()
    spy.mockImplementation((input, init) => {
      const reply = inner?.(input, init) ?? Promise.reject(new Error("no mock"))
      if (String(input) !== "/api/status" || release) return reply
      // Hold the first status call: it is the one that mints the cookie.
      return new Promise<Response>((resolve) => {
        release = () => void reply.then(resolve)
      })
    })
    const { unmount } = render(<Probe id="one" />)
    await waitFor(() => expect(release).toBeDefined())
    // Nothing else may race the cookie-minting request.
    expect(FakeEventSource.instances).toHaveLength(0)
    expect(spy.mock.calls.map(([u]) => String(u))).toEqual(["/api/status"])
    act(() => release?.())
    await screen.findByText("one:stopped")
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    expect(spy.mock.calls.map(([u]) => String(u)).slice(0, 2)).toEqual(["/api/status", "/api/projects"])
    unmount()
  })

  it("event_source_waits_for_a_successful_status", async () => {
    let fail = true
    installApi({
      "GET /api/projects": { body: PROJECTS },
      "GET /api/status": () => (fail ? { status: 502, body: {} } : { body: statusBody() }),
    })
    const { unmount } = render(<StatusWithRefresh />)
    await screen.findByText("error")
    expect(FakeEventSource.instances).toHaveLength(0)
    fail = false
    await userEvent.click(screen.getByRole("button", { name: "refresh" }))
    await screen.findByText("stopped")
    expect(FakeEventSource.instances).toHaveLength(1)
    unmount()
  })

  it("keeps_last_stack_failed_message_until_dismissed", async () => {
    installApi({
      "GET /api/projects": { body: PROJECTS },
      "GET /api/status": { body: statusBody() },
    })
    const { unmount } = render(<NoticeProbe />)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    act(() => FakeEventSource.instances[0]?.emit({ type: "stack_failed", title: "A failed", body: "b" }))
    act(() => FakeEventSource.instances[0]?.emit({ type: "queue_changed" }))
    await userEvent.click(await screen.findByRole("button", { name: "stack_failed:A failed" }))
    expect(await screen.findByText("no notice")).toBeInTheDocument()
    act(() => FakeEventSource.instances[0]?.emit({ type: "evicted", title: "Turn ended", body: "b" }))
    expect(await screen.findByRole("button", { name: "evicted:Turn ended" })).toBeInTheDocument()
    act(() => FakeEventSource.instances[0]?.emit({ type: "garbage" }))
    act(() => FakeEventSource.instances[0]?.onmessage?.(new MessageEvent("message", { data: "{not json" })))
    expect(screen.getByRole("button", { name: "evicted:Turn ended" })).toBeInTheDocument()
    unmount()
  })
})

function StatusWithRefresh() {
  const { status, error, refresh } = useStatus()
  return (
    <>
      <p>{error ? "error" : (status?.status ?? "loading")}</p>
      <button type="button" onClick={() => void refresh()}>
        refresh
      </button>
    </>
  )
}
