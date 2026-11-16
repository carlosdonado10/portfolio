"""Agent entrypoint: long-poll desired state, converge the box, report observed state."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orch_common.manifest import load_manifests
from orch_common.wire import DesiredState

from agent.client import ControlPlaneClient
from agent.driver import DockerComposeDriver
from agent.probe import HttpHealthProbe
from agent.reconciler import Reconciler

logger = logging.getLogger("agent")


class _Source(Protocol):
    async def next_desired(self, after: int) -> DesiredState: ...


class _Converger(Protocol):
    async def converge(self, desired: DesiredState) -> bool: ...

    async def watch_health(self, desired: DesiredState) -> None: ...

    async def report_crash(self, desired: DesiredState, error: str) -> None: ...


@dataclass(frozen=True)
class Config:
    control_plane_url: str
    projects_dir: Path
    repos_dir: Path
    include_hidden: bool


def config_from_env(env: Mapping[str, str]) -> Config:
    return Config(
        control_plane_url=env.get("ORCH_CONTROL_PLANE_URL", "http://control-plane:8001"),
        projects_dir=Path(env.get("ORCH_PROJECTS_DIR", "/srv/orch/projects")),
        repos_dir=Path(env.get("ORCH_REPOS_DIR", "/srv/orch/repos")),
        include_hidden=env.get("ORCH_INCLUDE_HIDDEN", "").lower() in {"1", "true"},
    )


async def _cycle(reconciler: _Converger, desired: DesiredState) -> None:
    try:
        if await reconciler.converge(desired):
            await reconciler.watch_health(desired)
    except Exception as e:
        # Best effort: tell the control plane, or its lease sits in STARTING until
        # the boot watchdog fires. A failing report must not mask the crash log.
        try:
            await reconciler.report_crash(desired, f"{type(e).__name__}: {e}")
        except Exception:
            logger.warning("could not report the crash of generation %s", desired.generation)
        logger.exception("reconcile cycle for generation %s crashed", desired.generation)


async def run(client: _Source, reconciler: _Converger) -> None:
    """Converge on every new desired generation; runs until cancelled.

    The first fetch uses ``after_generation=-1`` so a restarted agent re-converges to
    the current state at once. Stacks are deliberately left running on shutdown.
    """
    generation = -1
    current: asyncio.Task[None] | None = None
    try:
        while True:
            desired = await client.next_desired(generation)
            if desired.generation == generation:
                continue  # long-poll timeout with nothing new
            generation = desired.generation
            if current is not None:
                current.cancel()
                await asyncio.wait([current])
            logger.info("desired generation %s: active=%s", generation, desired.active)
            current = asyncio.create_task(_cycle(reconciler, desired))
    finally:
        if current is not None:
            current.cancel()
            await asyncio.wait([current])


async def _amain(cfg: Config) -> None:
    manifests = {m.id: m for m in load_manifests(cfg.projects_dir, cfg.include_hidden)}
    client = ControlPlaneClient(cfg.control_plane_url)
    probe = HttpHealthProbe()
    reconciler = Reconciler(
        manifests,
        DockerComposeDriver(cfg.repos_dir),
        probe,
        client.report,
        time.time,
        asyncio.sleep,
    )
    task = asyncio.create_task(run(client, reconciler))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    finally:
        await client.aclose()
        await probe.aclose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(_amain(config_from_env(os.environ)))


if __name__ == "__main__":
    main()
