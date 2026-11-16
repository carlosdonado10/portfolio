"""In-process SSE fan-out: per-session subscriber queues."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

Message = dict[str, Any]


class Hub:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[Message]]] = {}

    @asynccontextmanager
    async def subscribe(self, sid: str) -> AsyncIterator[AsyncGenerator[Message]]:
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self._subs.setdefault(sid, set()).add(queue)

        async def messages() -> AsyncGenerator[Message]:
            while True:
                yield await queue.get()

        it = messages()
        try:
            yield it
        finally:
            await it.aclose()
            subs = self._subs.get(sid)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    del self._subs[sid]

    async def publish(self, sid: str, msg: Message) -> None:
        for queue in tuple(self._subs.get(sid, ())):
            queue.put_nowait(dict(msg))

    async def broadcast(self, msg: Message) -> None:
        for sid in tuple(self._subs):
            await self.publish(sid, msg)

    def connected(self, sid: str) -> bool:
        return bool(self._subs.get(sid))
