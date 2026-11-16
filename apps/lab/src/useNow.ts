import { useEffect, useState } from "react"

/** Epoch seconds, re-rendered every `everyMs` while the component is mounted. */
export function useNow(everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), everyMs)
    return () => clearInterval(id)
  }, [everyMs])
  return now
}
