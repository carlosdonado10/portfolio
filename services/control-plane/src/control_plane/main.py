"""Control-plane entrypoint: public API (8000), agent API (8001) and the tick loop."""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Coroutine, Iterator, Sequence
from typing import Any, Protocol

import uvicorn
from fastapi import FastAPI
from orch_common.manifest import load_manifests

from control_plane.api_agent import create_agent_app
from control_plane.api_public import create_public_app
from control_plane.engine import Engine
from control_plane.hub import Hub
from control_plane.mailer import Mailer, NullMailer, ResendMailer
from control_plane.settings import Settings
from control_plane.store import Store

log = logging.getLogger(__name__)

PUBLIC_PORT = 8000
AGENT_PORT = 8001
# Containers listen on their private network; nginx only proxies the public port.
HOST = "0.0.0.0"  # noqa: S104


def build(settings: Settings) -> tuple[FastAPI, FastAPI, Engine]:
    manifests = {m.id: m for m in load_manifests(settings.projects_dir, settings.include_hidden)}
    store = Store(settings.db_path)
    mailer: Mailer = (
        ResendMailer(settings.resend_api_key, settings.email_from)
        if settings.resend_api_key and settings.email_from
        else NullMailer()
    )
    engine = Engine.load(
        store,
        Hub(),
        mailer,
        manifests,
        settings.lease.to_config(),
        public_base_url=settings.public_base_url,
    )
    public = create_public_app(engine, store, settings)
    return public, create_agent_app(engine), engine


class _Server(uvicorn.Server):
    """uvicorn server that leaves signal handling to ``serve``.

    Each Server.serve() installs its own SIGINT/SIGTERM handlers, so with two
    servers in one process the second would silently replace the first.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


class Runnable(Protocol):
    should_exit: bool

    async def serve(self) -> None: ...


async def _serve_one(server: Runnable) -> None:
    # uvicorn calls sys.exit(1) on a bind failure; SystemExit would tear through
    # the event loop instead of reaching run()'s accounting.
    try:
        await server.serve()
    except SystemExit as e:
        raise RuntimeError(f"server exited ({e.code})") from e


async def run(
    servers: Sequence[Runnable], ticker: Coroutine[Any, Any, None], stop: asyncio.Event
) -> int:
    """Run servers and ticker until one finishes or ``stop`` is set.

    Returns 0 for a requested shutdown, 1 if anything ended on its own (a crash,
    a bind failure or a clean return): never run half-alive.
    """
    tasks = [asyncio.ensure_future(_serve_one(s)) for s in servers]
    tasks.append(asyncio.ensure_future(ticker))
    waiter = asyncio.ensure_future(stop.wait())
    await asyncio.wait([*tasks, waiter], return_when=asyncio.FIRST_COMPLETED)
    clean = stop.is_set()
    for s in servers:
        s.should_exit = True
    waiter.cancel()
    tasks[-1].cancel()  # the ticker never returns on its own
    results = await asyncio.gather(*tasks, waiter, return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
            log.error("task ended with %r", r)
    return 0 if clean else 1


async def serve(settings: Settings) -> int:
    public, agent, engine = build(settings)

    def server(app: FastAPI, port: int) -> _Server:
        config = uvicorn.Config(app, host=HOST, port=port, proxy_headers=False, log_level="info")
        return _Server(config)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        return await run(
            [server(public, PUBLIC_PORT), server(agent, AGENT_PORT)], engine.run_ticks(), stop
        )
    finally:
        engine.close()


def main() -> None:
    raise SystemExit(asyncio.run(serve(Settings())))  # type: ignore[call-arg]  # env-populated


if __name__ == "__main__":
    main()
