import { useCallback, useEffect, useState, type FormEvent } from "react"

import { api, ApiError, type AdminOverview } from "../api"
import ErrorAlert from "../components/ErrorAlert"
import { copy } from "../copy"
import { useAction } from "../useAction"

const t = copy.admin

function Console({ onSignedOut }: { onSignedOut: () => void }) {
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const load = useCallback(async () => {
    try {
      setOverview(await api.adminOverview())
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onSignedOut()
    }
  }, [onSignedOut])
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load
    void load()
  }, [load])
  const { busy, error, run } = useAction(() => void load())

  return (
    <>
      <h2>{t.overview}</h2>
      <p className="actions">
        <button type="button" disabled={busy} onClick={() => void run(api.adminForceStop)}>
          {t.forceStop}
        </button>
        <button type="button" disabled={busy} onClick={() => void run(api.adminClearQueue)}>
          {t.clearQueue}
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={() => void load()}>
          {t.refresh}
        </button>
      </p>
      <p className="muted">
        {t.forceStopWhy} {t.clearQueueWhy}
      </p>
      <ErrorAlert message={error} />
      {overview ? (
        <>
          <h3>{t.state}</h3>
          <pre>{JSON.stringify(overview.state, null, 2)}</pre>
          <h3>{t.sessions}</h3>
          {overview.sessions.length === 0 ? (
            <p>{t.noSessions}</p>
          ) : (
            <ul>
              {overview.sessions.map((s) => (
                <li key={s.sid}>
                  {s.sid.slice(0, 8)} {s.email ?? ""} {s.ip ?? ""}
                </li>
              ))}
            </ul>
          )}
          <h3>{t.visits}</h3>
          {overview.recent_visits.length === 0 ? (
            <p>{t.noVisits}</p>
          ) : (
            <ul>
              {overview.recent_visits.map((v, i) => (
                <li key={`${i}-${v.sid}-${v.at}`}>
                  {new Date(v.at * 1000).toLocaleString()} {v.sid.slice(0, 8)} {v.path ?? ""}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : null}
    </>
  )
}

export default function Admin() {
  const [signedIn, setSignedIn] = useState(false)
  const [secret, setSecret] = useState("")
  const { busy, error, run } = useAction(() => setSignedIn(true))
  const signOut = useCallback(() => setSignedIn(false), [])
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(() => api.adminLogin(secret))
  }
  return (
    <section>
      <h2>{t.heading}</h2>
      {signedIn ? (
        <Console onSignedOut={signOut} />
      ) : (
        <form onSubmit={submit} className="stack">
          <p>{t.intro}</p>
          <label htmlFor="owner-secret">{t.secretLabel}</label>
          <input
            id="owner-secret"
            type="password"
            autoComplete="current-password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
          />
          <p className="muted">{t.loginWhy}</p>
          <button type="submit" disabled={busy || secret === ""}>
            {t.login}
          </button>
          <ErrorAlert message={error} />
        </form>
      )}
    </section>
  )
}
