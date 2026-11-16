import { Link } from "react-router"

import BoxPanel from "../components/BoxPanel"
import { copy } from "../copy"
import { useStatus } from "../useStatus"

export default function Catalog() {
  const { status, projects, error } = useStatus()
  return (
    <>
      <p className="lede">{copy.tagline}</p>
      {error ? <p className="muted">{copy.loadError}</p> : null}
      {status && projects ? <BoxPanel status={status} projects={projects} /> : <p>{copy.loading}</p>}

      <section aria-labelledby="projects-h">
        <h2 id="projects-h">{copy.catalog.heading}</h2>
        {projects?.length === 0 ? <p>{copy.catalog.emptyProjects}</p> : null}
        <ul className="grid">
          {projects?.map((p) => (
            <li key={p.id} className="card">
              <h3>{p.name}</h3>
              <p>{p.tagline}</p>
              <p className="muted">{copy.catalog.eta(p.expected_boot_s)}</p>
              <p className="actions">
                <Link className="button" to={`/p/${p.id}`}>
                  {copy.catalog.runLive}
                  <span className="sr-only"> {p.name}</span>
                </Link>
                <a href={p.demo_url}>{copy.catalog.demo}</a>
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="how-h">
        <h2 id="how-h">{copy.how.heading}</h2>
        <dl className="how">
          {copy.how.items.map((i) => (
            <div key={i.title}>
              <dt>{i.title}</dt>
              <dd>{i.body}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  )
}
