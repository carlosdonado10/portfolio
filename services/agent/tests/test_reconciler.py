import asyncio

import pytest
from agent.driver import ComposeError
from agent.reconciler import Reconciler
from orch_common.wire import DesiredState, ObservedState, StackStatus


class FakeDriver:
    def __init__(self, running=(), up_error=None):
        self.calls: list[tuple[str, str]] = []
        self._running = set(running)
        self.up_error = up_error

    async def up(self, m):
        self.calls.append(("up", m.id))
        if self.up_error:
            raise self.up_error
        self._running.add(m.id)

    async def down(self, m):
        self.calls.append(("down", m.id))
        self._running.discard(m.id)

    async def running(self):
        return set(self._running)


class ScriptedProbe:
    """Returns scripted answers in order, then repeats the last one."""

    def __init__(self, *answers):
        self.answers = list(answers)

    async def check(self, m):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class FakeTime:
    def __init__(self):
        self.now = 1000.0

    def clock(self):
        return self.now

    async def sleep(self, s):
        self.now += s


def build(manifests, driver, probe, **kw):
    reports: list[ObservedState] = []
    t = FakeTime()

    async def report(o):
        reports.append(o)

    r = Reconciler(manifests, driver, probe, report, t.clock, t.sleep, **kw)
    return r, reports, t


def statuses(reports):
    return [r.status for r in reports]


async def test_converge_starts_and_reports_ready(manifests):
    driver, probe = FakeDriver(), ScriptedProbe(False, True)
    r, reports, _ = build(manifests, driver, probe)
    assert await r.converge(DesiredState(active="a", generation=7)) is True
    assert statuses(reports) == [StackStatus.STARTING, StackStatus.READY]
    assert {o.generation for o in reports} == {7}
    assert {o.stack_id for o in reports} == {"a"}
    assert reports[0].at == 1000.0


async def test_converge_downs_other_running_first(manifests):
    driver = FakeDriver(running={"b"})
    r, _, _ = build(manifests, driver, ScriptedProbe(True))
    await r.converge(DesiredState(active="a", generation=1))
    assert driver.calls == [("down", "b"), ("up", "a")]


async def test_converge_none_downs_all_reports_stopped(manifests):
    driver = FakeDriver(running={"a", "b"})
    r, reports, _ = build(manifests, driver, ScriptedProbe(True))
    assert await r.converge(DesiredState(active=None, generation=3)) is False
    assert sorted(driver.calls) == [("down", "a"), ("down", "b")]
    assert len(reports) == 1
    assert reports[0].status is StackStatus.STOPPED
    assert reports[0].stack_id is None
    assert reports[0].generation == 3


async def test_running_project_without_manifest_is_left_alone(manifests):
    driver = FakeDriver(running={"ghost"})
    r, reports, _ = build(manifests, driver, ScriptedProbe(True))
    await r.converge(DesiredState(active=None, generation=1))
    assert driver.calls == []
    assert statuses(reports) == [StackStatus.STOPPED]


async def test_boot_timeout_downs_and_reports_failed(manifests):
    driver = FakeDriver()
    r, reports, t = build(manifests, driver, ScriptedProbe(False))
    assert await r.converge(DesiredState(active="a", generation=2)) is False
    assert driver.calls == [("up", "a"), ("down", "a")]
    assert statuses(reports) == [StackStatus.STARTING, StackStatus.FAILED]
    assert "10 seconds" in (reports[-1].error or "")
    assert t.now - 1000.0 >= 10


async def test_compose_error_reports_failed_with_message(manifests):
    driver = FakeDriver(up_error=ComposeError("boom: bad compose"))
    r, reports, _ = build(manifests, driver, ScriptedProbe(True))
    assert await r.converge(DesiredState(active="a", generation=2)) is False
    assert statuses(reports) == [StackStatus.STARTING, StackStatus.FAILED]
    assert reports[-1].error == "boom: bad compose"


async def test_compose_error_on_down_reports_failed(manifests):
    class BadDown(FakeDriver):
        async def down(self, m):
            raise ComposeError("cannot stop")

    r, reports, _ = build(manifests, BadDown(running={"b"}), ScriptedProbe(True))
    await r.converge(DesiredState(active="a", generation=2))
    assert statuses(reports) == [StackStatus.FAILED]
    assert reports[0].error == "cannot stop"


async def test_idempotent_when_already_running_and_healthy(manifests):
    driver = FakeDriver(running={"a"})
    r, reports, _ = build(manifests, driver, ScriptedProbe(True))
    assert await r.converge(DesiredState(active="a", generation=4)) is True
    assert ("up", "a") not in driver.calls
    assert statuses(reports) == [StackStatus.READY]


async def test_running_but_unhealthy_is_brought_up_again(manifests):
    driver = FakeDriver(running={"a"})
    r, reports, _ = build(manifests, driver, ScriptedProbe(False, False, True))
    assert await r.converge(DesiredState(active="a", generation=4)) is True
    assert ("up", "a") in driver.calls
    assert statuses(reports) == [StackStatus.STARTING, StackStatus.READY]


async def test_newer_generation_cancels_boot(manifests):
    driver, probe = FakeDriver(), ScriptedProbe(False)
    r, reports, t = build(manifests, driver, probe)
    gate = asyncio.Event()
    real_sleep = t.sleep

    async def slow_sleep(s):
        gate.set()
        await asyncio.sleep(3600)
        await real_sleep(s)

    r._sleep = slow_sleep
    task = asyncio.create_task(r.converge(DesiredState(active="a", generation=1)))
    await gate.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert statuses(reports) == [StackStatus.STARTING]


async def test_health_watch_restarts_once_then_fails(manifests):
    driver = FakeDriver(running={"a"})
    r, reports, _ = build(manifests, driver, ScriptedProbe(False), watch_interval_s=1)
    await r.watch_health(DesiredState(active="a", generation=5))
    assert driver.calls == [("down", "a"), ("up", "a"), ("down", "a")]
    assert statuses(reports) == [StackStatus.STARTING, StackStatus.FAILED]
    assert {o.generation for o in reports} == {5}


async def test_health_watch_success_resets_failure_counter(manifests):
    driver = FakeDriver(running={"a"})
    probe = ScriptedProbe(False, False, True, False, False, True)
    r, reports, t = build(manifests, driver, probe, watch_interval_s=1)

    async def stop_after_script(s):
        if not probe.answers[1:]:
            raise asyncio.CancelledError
        await t.sleep(s)

    r._sleep = stop_after_script
    with pytest.raises(asyncio.CancelledError):
        await r.watch_health(DesiredState(active="a", generation=5))
    assert driver.calls == []
    assert reports == []


async def test_health_watch_restart_that_recovers_keeps_watching(manifests):
    driver = FakeDriver(running={"a"})
    # 3 failures -> restart; boot probe healthy; then watch sees healthy until stopped
    probe = ScriptedProbe(False, False, False, True)
    r, reports, t = build(manifests, driver, probe, watch_interval_s=1)
    sleeps = 0

    async def limited(s):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 6:
            raise asyncio.CancelledError
        await t.sleep(s)

    r._sleep = limited
    with pytest.raises(asyncio.CancelledError):
        await r.watch_health(DesiredState(active="a", generation=5))
    assert driver.calls == [("down", "a"), ("up", "a")]
    assert statuses(reports) == [StackStatus.STARTING, StackStatus.READY]


async def test_health_watch_compose_error_reports_failed(manifests):
    driver = FakeDriver(running={"a"}, up_error=ComposeError("nope"))
    r, reports, _ = build(manifests, driver, ScriptedProbe(False), watch_interval_s=1)
    await r.watch_health(DesiredState(active="a", generation=5))
    assert statuses(reports) == [StackStatus.STARTING, StackStatus.FAILED]
    assert reports[-1].error == "nope"


async def test_watch_health_unknown_stack_is_a_noop(manifests):
    r, reports, _ = build(manifests, FakeDriver(), ScriptedProbe(True))
    await r.watch_health(DesiredState(active=None, generation=1))
    assert reports == []


async def test_unknown_stack_reports_failed(manifests):
    driver = FakeDriver()
    r, reports, _ = build(manifests, driver, ScriptedProbe(True))
    assert await r.converge(DesiredState(active="zzz", generation=9)) is False
    assert driver.calls == []
    assert statuses(reports) == [StackStatus.FAILED]
    assert reports[0].stack_id == "zzz"
    assert "unknown stack" in (reports[0].error or "")
