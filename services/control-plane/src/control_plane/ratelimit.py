"""Per-key token buckets with continuous refill."""


class TokenBucket:
    def __init__(self, rate_per_min: int) -> None:
        self._capacity = float(rate_per_min)
        self._per_s = rate_per_min / 60.0
        # key -> (tokens, last refill time)
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, now: float) -> bool:
        tokens, last = self._buckets.get(key, (self._capacity, now))
        tokens = min(self._capacity, tokens + max(0.0, now - last) * self._per_s)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[key] = (tokens, now)
        if len(self._buckets) > 10_000:
            self._prune(now)
        return allowed

    def _prune(self, now: float) -> None:
        """Drop buckets that have fully refilled: they are indistinguishable from new."""
        full = [
            k
            for k, (tokens, last) in self._buckets.items()
            if tokens + (now - last) * self._per_s >= self._capacity
        ]
        for k in full:
            del self._buckets[k]
