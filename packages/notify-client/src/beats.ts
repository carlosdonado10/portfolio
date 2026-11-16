/** Leading-edge throttle: the first activity posts at once, then at most one per interval. */
export function createBeatSender(
  post: () => void,
  intervalMs = 30000,
  now: () => number = Date.now,
): { onActivity(): void } {
  let last = -Infinity
  return {
    onActivity() {
      const t = now()
      if (t - last >= intervalMs) {
        last = t
        post()
      }
    },
  }
}
