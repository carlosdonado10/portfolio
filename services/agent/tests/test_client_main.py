import asyncio
import json
from pathlib import Path

import httpx
import pytest
from agent.__main__ import config_from_env, run
from agent.client import ControlPlaneClient
from orch_common.wire import DesiredState, ObservedState, StackStatus


def obs():
    return ObservedState(stack_id="a", status=StackStatus.READY, generation=3, at=1.0)


def client_for(handler):
    sleeps: list[float] = []

    async def sleep(s):
        sleeps.append(s)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ControlPlaneClient("http://cp:8001/", http, sleep), sleeps


async def test_next_desired_queries_after_generation():
    seen = []

    def handler(req):
        seen.append(req.url)
        return httpx.Response(200, json={"active": "a", "generation": 4})

    c, _ = client_for(handler)
    assert await c.next_desired(3) == DesiredState(active="a", generation=4)
    assert str(seen[0]) == "http://cp:8001/agent/desired?after_generation=3"


async def test_next_desired_retries_with_exponential_backoff_capped():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 8:
            if calls["n"] % 2:
                raise httpx.ConnectError("down")
            return httpx.Response(503)
        return httpx.Response(200, json={"active": None, "generation": 1})

    c, sleeps = client_for(handler)
    assert (await c.next_desired(-1)).generation == 1
    assert sleeps == [1, 2, 4, 8, 16, 30, 30, 30]


async def test_report_posts_json():
    seen = []

    def handler(req):
        seen.append((req.method, str(req.url), json.loads(req.content)))
        return httpx.Response(204)

    c, _ = client_for(handler)
    await c.report(obs())
    method, url, body = seen[0]
    assert (method, url) == ("POST", "http://cp:8001/agent/observed")
    assert body["status"] == "ready" and body["generation"] == 3 and body["stack_id"] == "a"


async def test_report_retries_on_connection_error_and_5xx():
    results = [httpx.ConnectError("x"), httpx.Response(500), httpx.Response(204)]

    def handler(req):
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    c, sleeps = client_for(handler)
    await c.report(obs())
    assert sleeps == [1, 2] and results == []


async def test_report_4xx_is_dropped_not_retried():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(422)

    c, sleeps = client_for(handler)
    await c.report(obs())
    assert len(calls) == 1 and sleeps == []


async def test_aclose():
    c, _ = client_for(lambda r: httpx.Response(204))
    await c.aclose()


def test_config_defaults_and_overrides():
    cfg = config_from_env({})
    assert cfg.control_plane_url == "http://control-plane:8001"
    assert cfg.projects_dir == Path("/srv/orch/projects")
    assert cfg.repos_dir == Path("/srv/orch/repos")
    assert cfg.include_hidden is False
    cfg = config_from_env(
        {
            "ORCH_CONTROL_PLANE_URL": "http://x:1",
            "ORCH_PROJECTS_DIR": "/p",
            "ORCH_REPOS_DIR": "/r",
            "ORCH_INCLUDE_HIDDEN": "True",
        }
    )
    assert (cfg.control_plane_url, cfg.include_hidden) == ("http://x:1", True)
    assert config_from_env({"ORCH_INCLUDE_HIDDEN": "1"}).include_hidden is True
    assert config_from_env({"ORCH_INCLUDE_HIDDEN": "0"}).include_hidden is False


class ScriptedSource:
    def __init__(self, *states):
        self.states = list(states)
        self.afters: list[int] = []

    async def next_desired(self, after):
        self.afters.append(after)
        await settle()  # let a freshly spawned converge task actually start
        if self.states:
            return self.states.pop(0)
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")


class RecordingConverger:
    def __init__(self, block_on=None, crash_on=None):
        self.block_on = block_on
        self.crash_on = crash_on
        self.events: list[tuple[str, int]] = []
        self.crashes: list[tuple[int, str]] = []
        self.report_error: Exception | None = None
        self.started = asyncio.Event()

    async def converge(self, d):
        self.events.append(("start", d.generation))
        self.started.set()
        if d.generation == self.crash_on:
            raise RuntimeError("kaboom")
        if d.generation == self.block_on:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.events.append(("cancelled", d.generation))
                raise
        self.events.append(("ready", d.generation))
        return True

    async def watch_health(self, d):
        self.events.append(("watch", d.generation))
        await asyncio.sleep(3600)

    async def report_crash(self, d, error):
        self.crashes.append((d.generation, error))
        if self.report_error is not None:
            raise self.report_error


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


async def test_run_startup_fetches_minus_one_and_converges():
    src = ScriptedSource(DesiredState(active="a", generation=5))
    conv = RecordingConverger()
    task = asyncio.create_task(run(src, conv))
    await until(lambda: ("watch", 5) in conv.events)
    assert src.afters == [-1, 5]
    assert conv.events == [("start", 5), ("ready", 5), ("watch", 5)]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_cancels_inflight_converge_on_newer_generation():
    src = ScriptedSource(
        DesiredState(active="a", generation=1), DesiredState(active="b", generation=2)
    )
    conv = RecordingConverger(block_on=1)
    task = asyncio.create_task(run(src, conv))
    await until(lambda: ("watch", 2) in conv.events)
    assert conv.events == [
        ("start", 1),
        ("cancelled", 1),
        ("start", 2),
        ("ready", 2),
        ("watch", 2),
    ]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_ignores_repeated_generation_and_survives_crash():
    src = ScriptedSource(
        DesiredState(active="a", generation=1),
        DesiredState(active="a", generation=1),
        DesiredState(active="b", generation=2),
    )
    conv = RecordingConverger(crash_on=1)
    task = asyncio.create_task(run(src, conv))
    await until(lambda: ("watch", 2) in conv.events)
    assert conv.events == [("start", 1), ("start", 2), ("ready", 2), ("watch", 2)]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_shutdown_cancels_current_task():
    src = ScriptedSource(DesiredState(active="a", generation=1))
    conv = RecordingConverger(block_on=1)
    task = asyncio.create_task(run(src, conv))
    await conv.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ("cancelled", 1) in conv.events


async def test_run_reports_failed_when_a_cycle_crashes():
    src = ScriptedSource(DesiredState(active="a", generation=1))
    conv = RecordingConverger(crash_on=1)
    task = asyncio.create_task(run(src, conv))
    await until(lambda: conv.crashes)
    assert conv.crashes == [(1, "RuntimeError: kaboom")]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_survives_a_failing_crash_report():
    src = ScriptedSource(
        DesiredState(active="a", generation=1), DesiredState(active="b", generation=2)
    )
    conv = RecordingConverger(crash_on=1)
    conv.report_error = RuntimeError("control plane down")
    task = asyncio.create_task(run(src, conv))
    await until(lambda: ("watch", 2) in conv.events)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
