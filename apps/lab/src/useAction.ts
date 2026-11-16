import { useCallback, useState } from "react"

import { ApiError } from "./api"
import { copy } from "./copy"

/** Wraps a mutating call: tracks busy state and keeps the server's error copy verbatim. */
export function useAction(onDone?: () => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(
    async (fn: () => Promise<unknown>) => {
      setBusy(true)
      setError(null)
      try {
        await fn()
        onDone?.()
      } catch (e) {
        if (e instanceof ApiError) setError(e.message || copy.errors.generic)
        else setError(copy.errors.network)
      } finally {
        setBusy(false)
      }
    },
    [onDone],
  )
  return { busy, error, run }
}
