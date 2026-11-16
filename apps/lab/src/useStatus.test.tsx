import { render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { FakeEventSource, installApi, PROJECTS, statusBody } from "./test-utils"
import { useStatus } from "./useStatus"

function Probe({ id }: { id: string }) {
  const { status } = useStatus()
  return <p>{`${id}:${status?.status ?? "loading"}`}</p>
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
})
