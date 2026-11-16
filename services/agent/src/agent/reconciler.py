"""Converge the box to the control plane's desired state, then keep it healthy."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from orch_common.manifest import Manifest
from orch_common.wire import DesiredState, ObservedState, StackStatus

from agent.driver import ComposeDriver, ComposeError
from agent.probe import HealthProbe

logger = logging.getLogger("agent.reconciler")


class Reconciler:
    def __init__(
        self,
        manifests: dict[str, Manifest],
        driver: ComposeDriver,
        probe: HealthProbe,
        report: Callable[[ObservedState], Awaitable[None]],
        clock: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
        *,
        watch_interval_s: float = 10.0,
        watch_failures: int = 3,
    ) -> None:
        self._manifests = manifests
        self._driver = driver
        self._probe = probe
        self._report = report
        self._clock = clock
        self._sleep = sleep
        self._watch_interval_s = watch_interval_s
        self._watch_failures = watch_failures

    async def _say(
        self, desired: DesiredState, status: StackStatus, error: str | None = None
    ) -> None:
        await self._report(
            ObservedState(
                stack_id=desired.active,
                status=status,
                generation=desired.generation,
                error=error,
                at=self._clock(),
            )
        )

    async def converge(self, desired: DesiredState) -> bool:
        """Make the box match ``desired``. Returns True iff the active stack ended READY."""
        active = desired.active
        try:
            for stack_id in sorted(await self._driver.running()):
                if stack_id == active:
                    continue
                other = self._manifests.get(stack_id)
                if other is None:
                    logger.warning("running project orch-%s has no manifest; downing", stack_id)
                    await self._driver.down_project(f"orch-{stack_id}")
                    continue
                await self._driver.down(other)
            if active is None:
                await self._say(desired, StackStatus.STOPPED)
                return False
            m = self._manifests.get(active)
            if m is None:
                await self._say(desired, StackStatus.FAILED, f"unknown stack {active!r}")
                return False
            if active in await self._driver.running() and await self._probe.check(m):
                await self._say(desired, StackStatus.READY)
                return True
            return await self._boot(desired, m)
        except ComposeError as e:
            await self._say(desired, StackStatus.FAILED, str(e))
            return False

    async def _boot(self, desired: DesiredState, m: Manifest) -> bool:
        await self._say(desired, StackStatus.STARTING)
        await self._driver.up(m)
        started = self._clock()
        while True:
            if await self._probe.check(m):
                await self._say(desired, StackStatus.READY)
                return True
            if self._clock() - started >= m.health.timeout_s:
                break
            await self._sleep(m.health.interval_s)
        await self._driver.down(m)
        await self._say(
            desired,
            StackStatus.FAILED,
            f"boot exceeded {m.health.timeout_s} seconds without a healthy response",
        )
        return False

    async def watch_health(self, desired: DesiredState) -> None:
        """While READY, probe periodically; restart once after repeated failures."""
        m = self._manifests.get(desired.active or "")
        if m is None:
            return
        failures = 0
        while True:
            await self._sleep(self._watch_interval_s)
            if await self._probe.check(m):
                failures = 0
                continue
            failures += 1
            if failures < self._watch_failures:
                continue
            logger.warning("stack %s unhealthy; restarting once", m.id)
            try:
                await self._driver.down(m)
                if not await self._boot(desired, m):
                    return
            except ComposeError as e:
                await self._say(desired, StackStatus.FAILED, str(e))
                return
            failures = 0
