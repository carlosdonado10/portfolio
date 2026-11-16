/** "m:ss" for a non-negative number of seconds. */
export function clock(totalSeconds: number): string {
  const s = Math.max(0, Math.ceil(totalSeconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}
