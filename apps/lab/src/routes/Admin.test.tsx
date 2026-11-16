import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { installApi } from "../test-utils"
import Admin from "./Admin"

const OVERVIEW = {
  state: { lease: null },
  sessions: [],
  recent_visits: [],
  observed: [
    {
      generation: 4,
      stack_id: "a",
      status: "failed",
      error: "boot exceeded 300 seconds without a healthy response",
      at: 1_700_000_000,
      source: "agent",
    },
    { generation: 4, stack_id: "a", status: "starting", error: null, at: 1_699_999_000, source: "agent" },
  ],
}

describe("Admin", () => {
  it("admin_shows_agent_reports_and_signs_out", async () => {
    const user = userEvent.setup()
    const spy = installApi({
      "POST /api/admin/login": { body: { ok: true } },
      "GET /api/admin/overview": { body: OVERVIEW },
      "POST /api/admin/logout": { status: 204, body: null },
    })
    render(<Admin />)
    await user.type(screen.getByLabelText(/owner secret/i), "pw")
    await user.click(screen.getByRole("button", { name: /sign in/i }))
    const list = await screen.findByRole("list", { name: /agent reports/i })
    expect(list).toHaveTextContent("boot exceeded 300 seconds")
    expect(list).toHaveTextContent("failed")
    expect(list).toHaveTextContent("generation 4")
    await user.click(screen.getByRole("button", { name: /sign out/i }))
    expect(await screen.findByLabelText(/owner secret/i)).toBeInTheDocument()
    expect(spy.mock.calls.some(([u, init]) => u === "/api/admin/logout" && init?.method === "POST")).toBe(true)
  })
})
