import { clock } from "../format"
import { useNow } from "../useNow"

export default function Countdown({ until, label }: { until: number; label: string }) {
  const now = useNow()
  return (
    <p className="countdown" role="timer">
      <span>{label}</span> <strong>{clock(until - now)}</strong>
    </p>
  )
}
