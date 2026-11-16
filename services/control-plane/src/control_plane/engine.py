"""Service layer: persists State, runs the pure core, executes its effects."""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from orch_common.manifest import Manifest
from orch_common.wire import DesiredState

from control_plane import copy
from control_plane.hub import Hub
from control_plane.lease import (
    Broadcast,
    Email,
    Event,
    LeaseConfig,
    Notify,
    SetDesired,
    State,
    Tick,
    decide,
)
from control_plane.mailer import Mailer
from control_plane.store import Store

log = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        store: Store,
        hub: Hub,
        mailer: Mailer,
        manifests: dict[str, Manifest],
        cfg: LeaseConfig,
        clock: Callable[[], float] = time.time,
        public_base_url: str = "",
        state: State | None = None,
    ) -> None:
        self._store = store
        self._hub = hub
        self._mailer = mailer
        self._manifests = manifests
        self._cfg = cfg
        self._clock = clock
        self._base = public_base_url.rstrip("/")
        self._state = state if state is not None else State()
        self._lock = asyncio.Lock()
        self._desired_changed = asyncio.Condition()
        self._mail_tasks: set[asyncio.Task[None]] = set()

    @classmethod
    def load(
        cls,
        store: Store,
        hub: Hub,
        mailer: Mailer,
        manifests: dict[str, Manifest],
        cfg: LeaseConfig,
        clock: Callable[[], float] = time.time,
        public_base_url: str = "",
    ) -> "Engine":
        # Visitors could not heartbeat while we were down, so presence/idle
        # timestamps are stale by the outage length: rebase them to now. The
        # window and grace clocks keep their wall-clock meaning, untouched.
        now = clock()
        state = store.load_state()
        lease = state.lease
        if lease is not None:
            lease = replace(lease, last_activity=now)
        queue = tuple(replace(q, last_seen=now) for q in state.queue)
        state = replace(state, lease=lease, queue=queue)
        return cls(store, hub, mailer, manifests, cfg, clock, public_base_url, state=state)

    def close(self) -> None:
        self._store.close()

    @property
    def state(self) -> State:
        return self._state

    @property
    def hub(self) -> Hub:
        return self._hub

    @property
    def manifests(self) -> dict[str, Manifest]:
        return self._manifests

    def desired(self) -> DesiredState:
        lease = self._state.lease
        return DesiredState(
            active=lease.stack_id if lease else None, generation=self._state.generation
        )

    async def dispatch(self, event: Event) -> State:
        async with self._lock:
            old = self._state
            transition = decide(old, event, self._cfg)  # Rejected propagates untouched
            self._store.save_state(transition.state)
            self._state = transition.state
            # Still under the lock so effects from successive events stay ordered;
            # every effect here is non-blocking (queue puts, scheduled mail).
            for effect in transition.effects:
                await self._execute(effect, old, transition.state)
            return transition.state

    async def flush(self) -> None:
        """Wait for in-flight emails (tests, graceful shutdown)."""
        while self._mail_tasks:
            await asyncio.gather(*tuple(self._mail_tasks), return_exceptions=True)

    async def wait_desired(self, after_generation: int, timeout: float) -> DesiredState:
        async def changed() -> None:
            async with self._desired_changed:
                await self._desired_changed.wait_for(
                    lambda: self._state.generation > after_generation
                )

        if self._state.generation <= after_generation:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(changed(), timeout)
        return self.desired()

    async def run_ticks(self, interval: float = 1.0) -> None:
        while True:
            try:
                await self.dispatch(Tick(self._clock()))
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(interval)

    # -- effects ---------------------------------------------------------

    async def _execute(self, effect: Any, old: State, new: State) -> None:
        if isinstance(effect, SetDesired):
            async with self._desired_changed:
                self._desired_changed.notify_all()
        elif isinstance(effect, Notify):
            await self._notify(effect, old, new)
        elif isinstance(effect, Broadcast):
            await self._hub.broadcast({"type": effect.kind})
        elif isinstance(effect, Email):
            self._email(effect)

    def _stack_for(self, sid: str, old: State, new: State) -> str | None:
        if new.lease is not None and new.lease.sid == sid:
            return new.lease.stack_id
        for entry in new.queue:
            if entry.sid == sid:
                return entry.stack_id
        return old.lease.stack_id if old.lease is not None else None

    def _name(self, stack_id: str | None) -> str:
        if stack_id is None:
            return "your project"
        manifest = self._manifests.get(stack_id)
        return manifest.name if manifest is not None else stack_id

    async def _notify(self, effect: Notify, old: State, new: State) -> None:
        stack_id = self._stack_for(effect.sid, old, new)
        msg: dict[str, Any] = {
            "type": effect.kind,
            "stack_id": stack_id,
            **effect.data,
            **copy.notification(effect.kind, self._name(stack_id), effect.data, self._cfg),
        }
        if effect.kind == "stack_failed":
            manifest = self._manifests.get(stack_id) if stack_id else None
            msg["demo_url"] = manifest.demo_url if manifest is not None else None
        await self._hub.publish(effect.sid, msg)

    def _email(self, effect: Email) -> None:
        address = self._store.get_email(effect.sid)
        if address is None:
            return
        if self._hub.connected(effect.sid) and effect.kind != "your_turn":
            return
        link = f"{self._base}/lab/p/{effect.stack_id}"
        subject, body = copy.email(effect.kind, self._name(effect.stack_id), link, self._cfg)
        task = asyncio.create_task(self._send(address, subject, body))
        self._mail_tasks.add(task)
        task.add_done_callback(self._mail_tasks.discard)

    async def _send(self, to: str, subject: str, body: str) -> None:
        try:
            await self._mailer.send(to, subject, body)
        except Exception:
            log.exception("email send failed")
