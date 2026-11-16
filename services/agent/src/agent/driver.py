"""Docker Compose driver: the only code in the agent that shells out to docker."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from orch_common.manifest import Manifest

logger = logging.getLogger("agent.driver")

PROJECT_PREFIX = "orch-"
_MISSING_IMAGE_MARKERS = ("pull access denied", "no such image", "image not found")


class ComposeError(Exception):
    """A docker compose invocation failed (message is operator-facing)."""


class ComposeDriver(Protocol):
    async def up(self, m: Manifest) -> None: ...

    async def down(self, m: Manifest) -> None: ...

    async def down_project(self, project_name: str) -> None:
        """Tear down a project by compose project name (no manifest needed)."""
        ...

    async def running(self) -> set[str]:
        """Ids (without the ``orch-`` prefix) of projects with running containers."""
        ...


def _prepare_hint(m: Manifest) -> str:
    return f"image not built for {m.id!r} — run `orchctl prepare {m.id}`"


class DockerComposeDriver:
    def __init__(
        self,
        repos_dir: Path,
        spawn: Callable[..., Any] = asyncio.create_subprocess_exec,
    ) -> None:
        self.repos_dir = repos_dir
        self._spawn = spawn

    async def _run(self, *argv: str) -> str:
        try:
            # Explicit argv, no shell; every element is a literal or a validated id/path.
            proc = await self._spawn(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out: bytes
            err: bytes
            try:
                out, err = await proc.communicate()
            except BaseException:
                # Cancelled or timed out: never orphan a running compose child, or a
                # later generation could race it and leave two stacks up.
                if proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                await proc.wait()
                raise
        except OSError as e:
            raise ComposeError(f"cannot run docker: {e}") from e
        if proc.returncode != 0:
            raise ComposeError(err.decode(errors="replace").strip() or f"{argv[0]} failed")
        return out.decode(errors="replace")

    async def up(self, m: Manifest) -> None:
        compose = m.compose_path(self.repos_dir)
        if m.repo and not compose.is_file():
            raise ComposeError(_prepare_hint(m))
        try:
            async with asyncio.timeout(m.health.timeout_s):
                await self._run(
                    "docker", "compose", "-p", m.project_name, "-f", str(compose),
                    "up", "-d", "--no-build", "--pull", "never", "--remove-orphans",
                )  # fmt: skip
        except TimeoutError as e:
            raise ComposeError(f"compose up exceeded {m.health.timeout_s} seconds") from e
        except ComposeError as e:
            if any(marker in str(e).lower() for marker in _MISSING_IMAGE_MARKERS):
                raise ComposeError(_prepare_hint(m)) from e
            raise

    async def down(self, m: Manifest) -> None:
        compose = m.compose_path(self.repos_dir)
        # Never `-v`: volumes (model caches) must survive. Without a compose file the
        # project can still be torn down by name via its labels.
        file_args = ["-f", str(compose)] if compose.is_file() else []
        await self._run(
            "docker", "compose", "-p", m.project_name, *file_args, "down", "--remove-orphans"
        )

    async def down_project(self, project_name: str) -> None:
        await self._run("docker", "compose", "-p", project_name, "down", "--remove-orphans")

    async def running(self) -> set[str]:
        out = await self._run("docker", "compose", "ls", "--format", "json")
        try:
            rows = json.loads(out) if out.strip() else []
        except json.JSONDecodeError:
            logger.warning("unparseable `docker compose ls` output: %r", out[:200])
            return set()
        if not isinstance(rows, list):
            return set()
        names = (r.get("Name") for r in rows if isinstance(r, dict))
        return {
            n[len(PROJECT_PREFIX) :]
            for n in names
            if isinstance(n, str) and n.startswith(PROJECT_PREFIX)
        }
