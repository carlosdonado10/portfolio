import { webUrl } from "../api"
import { copy } from "../copy"
import type { Notice } from "../useStatus"

/** A push the status poll can't show (boot failed, turn ended), kept until dismissed. */
export default function NoticeBanner({ notice, onDismiss }: { notice: Notice; onDismiss: () => void }) {
  const demo = webUrl(notice.demo_url)
  return (
    <section role="alert" className="card notice">
      <h2>{notice.title}</h2>
      <p>{notice.body}</p>
      {demo ? (
        <p>
          <a href={demo}>{copy.notice.demo}</a>
        </p>
      ) : null}
      <button type="button" className="secondary" onClick={onDismiss}>
        {copy.notice.dismiss}
      </button>
    </section>
  )
}
