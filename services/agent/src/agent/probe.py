"""Entry-service health probe over the shared docker network."""

from __future__ import annotations

from typing import Protocol

import httpx
from orch_common.manifest import Manifest

PROBE_TIMEOUT_S = 2.0


class HealthProbe(Protocol):
    async def check(self, m: Manifest) -> bool: ...


class HttpHealthProbe:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient()

    async def check(self, m: Manifest) -> bool:
        url = f"http://{m.entry_alias}:{m.entry.port}{m.base_path.rstrip('/')}{m.health.path}"
        try:
            r = await self._client.get(url, timeout=PROBE_TIMEOUT_S)
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    async def aclose(self) -> None:
        await self._client.aclose()
