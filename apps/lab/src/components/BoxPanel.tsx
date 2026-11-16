import type { Project, StatusBody } from "../api"
import { copy } from "../copy"
import Countdown from "./Countdown"
import QueueList from "./QueueList"

export default function BoxPanel({
  status,
  projects,
}: {
  status: StatusBody
  projects: Project[]
}) {
  const active = projects.find((p) => p.id === status.active)
  const name = active?.name ?? status.active ?? ""
  const holder =
    status.me.role === "holder" ? copy.box.youHold : (status.holder_alias ?? copy.box.youHold)
  let line: string = copy.box.idle
  if (status.active) {
    if (status.status === "starting") line = copy.box.starting(name)
    else line = copy.box.runningFor(name, holder)
  }
  return (
    <section aria-labelledby="box-h" className="card">
      <h2 id="box-h">{copy.box.heading}</h2>
      <p>{line}</p>
      {status.grace_deadline !== null ? (
        <Countdown until={status.grace_deadline} label={copy.box.grace} />
      ) : status.window_ends_at !== null ? (
        <Countdown until={status.window_ends_at} label={copy.box.window} />
      ) : null}
      <QueueList status={status} projects={projects} />
    </section>
  )
}
