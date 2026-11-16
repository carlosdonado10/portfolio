"""Control-plane entrypoint: public API (8000), agent API (8001) and the tick loop."""

import asyncio

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


async def serve(settings: Settings) -> None:
    public, agent, engine = build(settings)

    def server(app: FastAPI, port: int) -> uvicorn.Server:
        config = uvicorn.Config(app, host=HOST, port=port, proxy_headers=False, log_level="info")
        return uvicorn.Server(config)

    # Any task ending (even cleanly) is fatal: never run half-alive.
    await asyncio.gather(
        server(public, PUBLIC_PORT).serve(),
        server(agent, AGENT_PORT).serve(),
        engine.run_ticks(),
    )
    raise SystemExit(1)


def main() -> None:
    try:
        asyncio.run(serve(Settings()))  # type: ignore[call-arg]  # env-populated
    except KeyboardInterrupt:
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
