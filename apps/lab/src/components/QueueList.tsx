import type { Project, StatusBody } from "../api"
import { copy } from "../copy"

export default function QueueList({
  status,
  projects,
}: {
  status: StatusBody
  projects: Project[]
}) {
  const nameOf = (id: string) => projects.find((p) => p.id === id)?.name ?? id
  return (
    <section aria-labelledby="queue-h">
      <h3 id="queue-h">{copy.box.queueHeading}</h3>
      {status.queue.length === 0 ? (
        <p>{copy.box.queueEmpty}</p>
      ) : (
        <ol aria-labelledby="queue-h" className="queue">
          {status.queue.map((q, i) => (
            <li key={`${i}-${q.alias}`} className={q.me ? "queue__me" : undefined}>
              {q.alias}
              {q.me ? ` ${copy.box.me}` : ""} <span className="muted">{copy.box.queueFor(nameOf(q.stack_id))}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
