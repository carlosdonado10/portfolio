import { screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { installApi, PROJECTS, renderAt, statusBody } from "../test-utils"

describe("Catalog", () => {
  it("catalog_marks_me_in_queue", async () => {
    installApi({
      "GET /api/projects": { body: PROJECTS },
      "GET /api/status": {
        body: statusBody({
          active: "b",
          status: "ready",
          holder_alias: "Quiet Otter",
          queue: [
            { alias: "Calm Fox", stack_id: "a", me: false },
            { alias: "Brave Heron", stack_id: "a", me: true },
          ],
          me: { role: "queued", position: 2, alias: "Brave Heron" },
        }),
      },
    })
    renderAt("/")
    const list = await screen.findByRole("list", { name: /queue/i })
    const items = within(list).getAllByRole("listitem")
    expect(items[0]).not.toHaveTextContent("(Me)")
    expect(items[1]).toHaveTextContent("Brave Heron (Me)")
    expect(screen.getByRole("heading", { name: "Alpha RAG" })).toBeInTheDocument()
    expect(screen.getByText(/Quiet Otter/)).toBeInTheDocument()
  })

  it("catalog_tagline_counts_projects_and_hides_missing_demo", async () => {
    installApi({
      "GET /api/projects": { body: [PROJECTS[0], { ...PROJECTS[1], demo_url: null }] },
      "GET /api/status": { body: statusBody() },
    })
    renderAt("/")
    expect(await screen.findByText(/^2 machine-learning projects, one small server/i)).toBeInTheDocument()
    expect(screen.queryByText(/five/i)).not.toBeInTheDocument()
    expect(screen.getAllByRole("link", { name: /demo/i })).toHaveLength(1)
  })

  it("how_it_works_describes_the_agent_accurately", async () => {
    installApi({ "GET /api/projects": { body: PROJECTS }, "GET /api/status": { body: statusBody() } })
    renderAt("/")
    expect(await screen.findByText(/holds the Docker socket/i)).toBeInTheDocument()
    expect(screen.queryByText(/listens on a private socket/i)).not.toBeInTheDocument()
  })
})
