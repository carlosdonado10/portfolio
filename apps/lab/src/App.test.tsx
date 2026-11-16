import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"

import App from "./App"
import { FakeEventSource, installApi, PROJECTS, statusBody } from "./test-utils"

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

async function stream() {
  await screen.findByRole("button", { name: /run alpha rag live/i })
  const es = FakeEventSource.instances[0]
  if (!es) throw new Error("no event source")
  return es
}

describe("App notices", () => {
  it("stack_failed_push_shows_banner_with_demo_link_until_dismissed", async () => {
    const user = userEvent.setup()
    // By the time the push lands the box has already moved on: status is idle.
    installApi({ "GET /api/projects": { body: PROJECTS }, "GET /api/status": { body: statusBody() } })
    renderApp("/p/a")
    const es = await stream()
    act(() =>
      es.emit({
        type: "stack_failed",
        stack_id: "a",
        title: "Alpha RAG failed to start",
        body: "Alpha RAG did not become healthy in time.",
        demo_url: "https://demo.example/a",
      }),
    )
    const banner = await screen.findByRole("alert")
    expect(banner).toHaveTextContent("Alpha RAG failed to start")
    expect(banner).toHaveTextContent("did not become healthy")
    const demo = screen.getAllByRole("link", { name: /demo/i }).find((l) => banner.contains(l))
    expect(demo).toHaveAttribute("href", "https://demo.example/a")
    await user.click(screen.getByRole("button", { name: /dismiss/i }))
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("evicted_banner_without_demo_and_unsafe_demo_urls_dropped", async () => {
    installApi({ "GET /api/projects": { body: PROJECTS }, "GET /api/status": { body: statusBody() } })
    renderApp("/p/a")
    const es = await stream()
    act(() =>
      es.emit({
        type: "stack_failed",
        title: "Failed",
        body: "b",
        demo_url: "javascript:alert(1)",
      }),
    )
    const banner = await screen.findByRole("alert")
    expect(banner.querySelector("a")).toBeNull()
    act(() => es.emit({ type: "evicted", title: "Your turn on Alpha RAG ended", body: "b" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Your turn on Alpha RAG ended")
  })
})
