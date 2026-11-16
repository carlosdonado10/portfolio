"""HTTP client for the control plane's internal agent API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx
from orch_common.wire import DesiredState, ObservedState

logger = logging.getLogger("agent.client")

LONG_POLL_READ_TIMEOUT_S = 35.0  # server long-poll is ~25 s
BACKOFF_START_S = 1.0
BACKOFF_CAP_S = 30.0


class ControlPlaneClient:
    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()
        self._sleep = sleep

    async def _backoff(self, delay: float, why: str) -> float:
        logger.warning("control plane unavailable (%s); retrying in %.0fs", why, delay)
        await self._sleep(delay)
        return min(delay * 2, BACKOFF_CAP_S)

    async def next_desired(self, after: int) -> DesiredState:
        delay = BACKOFF_START_S
        while True:
            try:
                r = await self._client.get(
                    f"{self._base}/agent/desired",
                    params={"after_generation": after},
                    timeout=LONG_POLL_READ_TIMEOUT_S,
                )
                r.raise_for_status()
                return DesiredState.model_validate(r.json())
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                delay = await self._backoff(delay, type(e).__name__)

    async def report(self, o: ObservedState) -> None:
        delay = BACKOFF_START_S
        while True:
            try:
                r = await self._client.post(
                    f"{self._base}/agent/observed", json=o.model_dump(mode="json"), timeout=10.0
                )
            except httpx.TransportError as e:
                delay = await self._backoff(delay, type(e).__name__)
                continue
            if r.status_code >= 500:
                delay = await self._backoff(delay, f"HTTP {r.status_code}")
                continue
            if r.status_code >= 400:
                logger.error("control plane rejected report (HTTP %s); dropping", r.status_code)
            return

    async def aclose(self) -> None:
        await self._client.aclose()
