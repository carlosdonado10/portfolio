import { useEffect, useRef } from "react"
import { Link, useParams } from "react-router"

import { api, webUrl, type Project, type StatusBody } from "../api"
import BootProgress from "../components/BootProgress"
import BoxPanel from "../components/BoxPanel"
import Countdown from "../components/Countdown"
import EmailForm from "../components/EmailForm"
import ErrorAlert from "../components/ErrorAlert"
import { copy } from "../copy"
import { useAction } from "../useAction"
import { useStatus } from "../useStatus"

const t = copy.interstitial

function DemoLink({ project }: { project: Project }) {
  const href = webUrl(project.demo_url)
  if (!href) return null
  return (
    <p>
      <a href={href}>{t.demo}</a> <span className="muted">{t.demoNote}</span>
    </p>
  )
}

function View({
  project,
  projects,
  status,
  refresh,
}: {
  project: Project
  projects: Project[]
  status: StatusBody
  refresh: () => Promise<void>
}) {
  const { busy, error, run } = useAction(() => void refresh())
  const redirected = useRef(false)
  const { me } = status
  const mine = me.role === "holder" && status.active === project.id
  const other = projects.find((p) => p.id === status.active)

  useEffect(() => {
    if (mine && status.status === "ready" && !redirected.current) {
      redirected.current = true
      window.location.assign(`/p/${project.id}/`)
    }
  }, [mine, status.status, project.id])

  const start = (p: Project, label: string) => (
    <button type="button" disabled={busy} onClick={() => void run(() => api.start(p.id))}>
      {busy ? t.working : label}
    </button>
  )
  const stop = (
    <p>
      <button type="button" className="secondary" disabled={busy} onClick={() => void run(() => api.stop())}>
        {t.stop}
      </button>{" "}
      <span className="muted">{t.stopWhy}</span>
    </p>
  )

  // A boot failure is shown by the app-wide notice from the SSE push: by the time
  // the status poll runs, the lease has already been released or handed on.
  let body
  if (mine && status.status === "ready") {
    body = (
      <>
        <h2>{t.ready.heading(project.name)}</h2>
        <p>{t.ready.opening}</p>
      </>
    )
  } else if (mine) {
    body = (
      <>
        <h2>{t.starting.heading(project.name)}</h2>
        <BootProgress expectedS={project.expected_boot_s} />
        <p>{t.starting.why}</p>
        {stop}
      </>
    )
  } else if (me.role === "holder" && other) {
    body = (
      <>
        <h2>{t.switchTo.running(other.name)}</h2>
        {status.window_ends_at !== null ? (
          <Countdown until={status.window_ends_at} label={copy.box.window} />
        ) : null}
        <p>{t.switchTo.why}</p>
        <p className="actions">
          {start(project, t.switchTo.button(project.name))}
          <Link to={`/p/${other.id}`}>{t.switchTo.keep(other.name)}</Link>
        </p>
        <DemoLink project={project} />
      </>
    )
  } else if (me.role === "queued" && me.position !== null) {
    const queuedFor = status.queue.find((q) => q.me)
    const target = projects.find((p) => p.id === queuedFor?.stack_id)
    body = (
      <>
        <h2>{t.queued.heading}</h2>
        <p>{t.queued.position(me.position, me.alias ?? "")}</p>
        {target ? <p>{t.queued.forProject(target.name)}</p> : null}
        <p>{t.queued.estimate(me.position, status.lease)}</p>
        <p className="muted">{t.queued.stayHint}</p>
        <EmailForm />
        <p>
          <button type="button" className="secondary" disabled={busy} onClick={() => void run(() => api.leave())}>
            {t.queued.leave}
          </button>
        </p>
        <DemoLink project={project} />
      </>
    )
  } else if (status.active) {
    body = (
      <>
        <h2>{project.name}</h2>
        <p>{t.busy(other?.name ?? status.active, status.holder_alias ?? "another visitor")}</p>
        {status.window_ends_at !== null ? (
          <Countdown until={status.window_ends_at} label={copy.box.window} />
        ) : null}
        <p>{t.busyQueue(status.queue.length)}</p>
        <p>{start(project, t.join(project.name))}</p>
        <p className="muted">{t.busyHint(status.lease)}</p>
        <DemoLink project={project} />
      </>
    )
  } else {
    body = (
      <>
        <h2>{project.name}</h2>
        <p>{project.tagline}</p>
        <p>{t.eta(project.expected_boot_s)}</p>
        <p>{start(project, t.start(project.name))}</p>
        <p className="muted">{t.startWhy}</p>
        <DemoLink project={project} />
      </>
    )
  }

  return (
    <>
      <section className="card">
        {body}
        <ErrorAlert message={error} />
      </section>
      <BoxPanel status={status} projects={projects} />
    </>
  )
}

export default function Interstitial() {
  const { id } = useParams()
  const { status, projects, error, projectsFailed, refresh } = useStatus()
  const project = projects?.find((p) => p.id === id)
  return (
    <>
      <p>
        <Link to="/">{t.back}</Link>
      </p>
      {error ? <p className="muted">{copy.loadError}</p> : null}
      {projectsFailed && !projects ? (
        <section className="card">
          <p role="alert" className="error">
            {copy.projectsFailed.body}
          </p>
          <button type="button" onClick={() => void refresh()}>
            {copy.projectsFailed.retry}
          </button>
        </section>
      ) : !status || !projects ? (
        <p>{copy.loading}</p>
      ) : !project ? (
        <p>{t.unknownProject}</p>
      ) : (
        <View project={project} projects={projects} status={status} refresh={refresh} />
      )}
    </>
  )
}
