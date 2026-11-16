import { useState, type FormEvent } from "react"

import { api } from "../api"
import { copy } from "../copy"
import { useAction } from "../useAction"
import ErrorAlert from "./ErrorAlert"

export default function EmailForm() {
  const [email, setEmail] = useState("")
  const [saved, setSaved] = useState(false)
  const { busy, error, run } = useAction(() => setSaved(true))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(() => api.email(email))
  }
  return (
    <form onSubmit={submit} className="stack">
      <label htmlFor="notify-email">{copy.interstitial.email.label}</label>
      <input
        id="notify-email"
        type="email"
        autoComplete="email"
        value={email}
        aria-describedby="notify-email-why"
        onChange={(e) => setEmail(e.target.value)}
      />
      <p id="notify-email-why" className="muted">
        {copy.interstitial.email.why}
      </p>
      <button type="submit" disabled={busy || email === ""}>
        {copy.interstitial.email.submit}
      </button>
      <ErrorAlert message={error} />
      {saved ? <p role="status">{copy.interstitial.email.saved}</p> : null}
    </form>
  )
}
