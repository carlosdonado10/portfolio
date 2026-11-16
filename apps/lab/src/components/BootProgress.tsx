import { copy } from "../copy"
import { useNow } from "../useNow"
import { useState } from "react"

/** Determinate bar against the manifest's expected boot time, capped at 95% until the server says ready. */
export default function BootProgress({ expectedS }: { expectedS: number }) {
  const [startedAt] = useState(() => Date.now() / 1000)
  const now = useNow()
  const elapsed = Math.max(0, now - startedAt)
  const pct = Math.min(95, Math.floor((elapsed / Math.max(1, expectedS)) * 100))
  return (
    <div>
      <label htmlFor="boot-progress">{copy.interstitial.starting.progress}</label>
      <progress id="boot-progress" max={100} value={pct} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        {copy.interstitial.starting.pct(pct)}
      </progress>
      <span className="muted"> {copy.interstitial.starting.pct(pct)}</span>
      {elapsed > expectedS ? <p className="muted">{copy.interstitial.starting.overrun}</p> : null}
    </div>
  )
}
