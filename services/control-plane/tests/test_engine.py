import asyncio

import pytest
from control_plane import copy
from control_plane.engine import Engine
from control_plane.hub import Hub
from control_plane.lease import (
    AdminForceStop,
    LeaseConfig,
    Observed,
    Rejected,
    StartRequested,
    StopRequested,
    Tick,
)
from control_plane.store import Store
from orch_common.manifest import Manifest
from orch_common.wire import StackStatus

CFG = LeaseConfig()


def manifest(id_, name, demo_url=None):
    return Manifest.model_validate(
        {
            "id": id_,
            "name": name,
            "compose": "docker-compose.yml",
            "entry": {"service": "web", "port": 80},
            "health": {},
            "expected_boot_s": 10,
            "demo_url": demo_url,
        }
    )


MANIFESTS = {
    "a": manifest("a", "Alpha Lab", "https://demo.example/a"),
    "b": manifest("b", "Beta Lab"),
}


class FakeMailer:
    def __init__(self):
        self.sent = []

    async def send(self, to, subject, body):
        self.sent.append((to, subject, body))


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def parts(tmp_path):
    store = Store(tmp_path / "o.sqlite")
    hub = Hub()
    mailer = FakeMailer()
    clock = Clock()
    eng = Engine(store, hub, mailer, MANIFESTS, CFG, clock, public_base_url="https://x.dev/")
    return eng, store, hub, mailer, clock


async def drain(eng):
    await eng.flush()


async def test_engine_dispatch_persists_and_notifies(parts):
    eng, store, hub, _, _ = parts
    async with hub.subscribe("s1") as sub:
        await eng.dispatch(StartRequested("s1", "a", 0.0))
        msg = await anext(sub)
    assert store.load_state().lease.sid == "s1"
    assert msg["type"] == "stack_starting"
    assert msg["stack_id"] == "a"
    assert msg["body"]
    assert "Alpha Lab" in msg["title"] + msg["body"]


async def test_engine_broadcast_reaches_everyone(parts):
    eng, _, hub, _, _ = parts
    async with hub.subscribe("other") as sub:
        await eng.dispatch(StartRequested("s1", "a", 0.0))
        assert await anext(sub) == {"type": "queue_changed"}


async def test_engine_rejected_propagates_and_does_not_save(parts):
    eng, store, *_ = parts
    with pytest.raises(Rejected):
        await eng.dispatch(StopRequested("nobody", 0.0))
    assert store.load_state().generation == 0


async def test_engine_wait_desired_wakes_on_change(parts):
    eng, *_ = parts
    waiter = asyncio.create_task(eng.wait_desired(0, 5))
    await asyncio.sleep(0)
    assert not waiter.done()
    await eng.dispatch(StartRequested("s1", "a", 0.0))
    desired = await asyncio.wait_for(waiter, 1)
    assert desired.active == "a"
    assert desired.generation == 1


async def test_engine_wait_desired_returns_immediately_when_ahead(parts):
    eng, *_ = parts
    await eng.dispatch(StartRequested("s1", "a", 0.0))
    assert (await asyncio.wait_for(eng.wait_desired(0, 5), 1)).active == "a"


async def test_engine_wait_desired_times_out(parts):
    eng, *_ = parts
    desired = await eng.wait_desired(0, 0.01)
    assert desired.active is None
    assert desired.generation == 0


async def test_engine_restart_preserves_state_and_clock(tmp_path):
    db = tmp_path / "o.sqlite"
    store, hub, mailer = Store(db), Hub(), FakeMailer()
    eng = Engine(store, hub, mailer, MANIFESTS, CFG, Clock())
    await eng.dispatch(StartRequested("s1", "a", 0.0))
    await eng.dispatch(Observed("a", StackStatus.READY, eng.state.generation, 0.0))
    await eng.dispatch(StartRequested("s2", "b", 1.0))
    before = eng.state
    reborn = Engine.load(Store(db), Hub(), FakeMailer(), MANIFESTS, CFG, Clock(100.0))
    await reborn.dispatch(Tick(100.0))
    assert reborn.state.lease == before.lease
    assert reborn.state.generation == before.generation
    assert reborn.state.lease.grace_deadline is None
    assert reborn.desired().active == "a"


async def test_engine_desired_when_idle(parts):
    eng, *_ = parts
    assert eng.desired().active is None


async def test_email_sent_when_not_connected(parts):
    eng, store, _, mailer, _ = parts
    store.ensure_session("s1", "ip")
    store.set_email("s1", "v@x.co")
    await eng.dispatch(StartRequested("s1", "a", 0.0, has_email=True))
    await eng.dispatch(Observed("a", StackStatus.READY, eng.state.generation, 1.0))
    await drain(eng)
    [(to, subject, body)] = mailer.sent
    assert to == "v@x.co"
    assert "Alpha Lab" in subject + body
    assert "https://x.dev/lab/p/a" in body


async def test_email_skipped_when_connected(parts):
    eng, store, hub, mailer, _ = parts
    store.ensure_session("s1", "ip")
    store.set_email("s1", "v@x.co")
    async with hub.subscribe("s1"):
        await eng.dispatch(StartRequested("s1", "a", 0.0, has_email=True))
        await eng.dispatch(Observed("a", StackStatus.READY, eng.state.generation, 1.0))
        await drain(eng)
    assert mailer.sent == []


async def test_your_turn_email_sent_even_when_connected(parts):
    eng, store, hub, mailer, _ = parts
    store.ensure_session("s2", "ip")
    store.set_email("s2", "w@x.co")
    await eng.dispatch(StartRequested("s1", "a", 0.0))
    await eng.dispatch(StartRequested("s2", "b", 1.0, has_email=True))
    async with hub.subscribe("s2"):
        await eng.dispatch(StopRequested("s1", 2.0))
        await drain(eng)
    [(to, _, body)] = mailer.sent
    assert to == "w@x.co"
    assert "Beta Lab" in body
    assert "/lab/p/b" in body


async def test_email_skipped_without_stored_address(parts):
    eng, _, _, mailer, _ = parts
    await eng.dispatch(StartRequested("s1", "a", 0.0, has_email=True))
    await eng.dispatch(Observed("a", StackStatus.READY, eng.state.generation, 1.0))
    await drain(eng)
    assert mailer.sent == []


async def test_mailer_failure_never_breaks_dispatch(tmp_path):
    class Boom:
        async def send(self, to, subject, body):
            raise RuntimeError("smtp down")

    store = Store(tmp_path / "o.sqlite")
    store.set_email("s1", "v@x.co")
    eng = Engine(store, Hub(), Boom(), MANIFESTS, CFG, Clock())
    await eng.dispatch(StartRequested("s1", "a", 0.0, has_email=True))
    await eng.dispatch(Observed("a", StackStatus.READY, eng.state.generation, 1.0))
    await eng.flush()
    assert eng.state.status == StackStatus.READY


async def test_evicted_notify_resolves_stack_from_old_state(parts):
    eng, _, hub, _, _ = parts
    await eng.dispatch(StartRequested("s1", "a", 0.0))
    async with hub.subscribe("s1") as sub:
        await eng.dispatch(AdminForceStop(1.0))
        msg = await anext(sub)
    assert msg["type"] == "evicted"
    assert msg["stack_id"] == "a"
    assert "Alpha Lab" in msg["title"] + msg["body"]


async def test_stack_failed_includes_demo_url(parts):
    eng, _, hub, _, _ = parts
    await eng.dispatch(StartRequested("s1", "a", 0.0))
    async with hub.subscribe("s1") as sub:
        await eng.dispatch(Observed("a", StackStatus.FAILED, eng.state.generation, 1.0, "boom"))
        msg = await anext(sub)
    assert msg["type"] == "stack_failed"
    assert msg["error"] == "boom"
    assert msg["demo_url"] == "https://demo.example/a"
    assert "demo" in msg["body"].lower()


async def test_unknown_manifest_falls_back_to_id(parts):
    eng, _, hub, _, _ = parts
    async with hub.subscribe("s1") as sub:
        await eng.dispatch(StartRequested("s1", "zzz", 0.0))
        msg = await anext(sub)
    assert msg["stack_id"] == "zzz"
    assert "zzz" in msg["body"] + msg["title"]


async def test_queued_notify_uses_queue_entry_stack(parts):
    eng, _, hub, _, _ = parts
    await eng.dispatch(StartRequested("s1", "a", 0.0))
    async with hub.subscribe("s2") as sub:
        await eng.dispatch(StartRequested("s2", "b", 1.0))
        msg = await anext(sub)
    assert msg["type"] == "queue_changed"
    assert msg["stack_id"] == "b"


async def test_run_ticks_survives_exception(parts, monkeypatch):
    eng, *_ = parts
    calls = []
    real = eng.dispatch

    async def flaky(event):
        calls.append(event)
        if len(calls) == 1:
            raise RuntimeError("tick blew up")
        return await real(event)

    monkeypatch.setattr(eng, "dispatch", flaky)
    task = asyncio.create_task(eng.run_ticks(0.001))
    for _ in range(100):
        await asyncio.sleep(0.005)
        if len(calls) >= 3:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 3
    assert all(isinstance(c, Tick) for c in calls)


@pytest.mark.parametrize(
    "kind",
    [
        "queue_changed",
        "your_turn",
        "stack_starting",
        "stack_ready",
        "grace_started",
        "grace_cancelled",
        "evicted",
        "stack_failed",
    ],
)
def test_every_kind_has_copy(kind):
    out = copy.notification(kind, "X", {})
    assert out["title"]
    assert out["body"]
    assert "X" in out["title"] + out["body"] or kind == "queue_changed"


def test_copy_uses_configured_durations_and_no_project_names():
    cfg = LeaseConfig(window_s=300, grace_s=60)
    body = copy.notification("your_turn", "X", {}, cfg)["body"]
    assert "5 minutes" in body
    subject, text = copy.email("stack_ready", "X", "https://l/p", cfg)
    assert "https://l/p" in text and "X" in subject + text
    for kind in ("your_turn", "stack_ready", "stack_failed"):
        s, t = copy.email(kind, "X", "https://l")
        assert s and t
    with pytest.raises(KeyError):
        copy.email("nope", "X", "l")
