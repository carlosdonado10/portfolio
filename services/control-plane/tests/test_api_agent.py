import asyncio

import httpx
import pytest
from control_plane.api_agent import create_agent_app
from control_plane.engine import Engine
from control_plane.hub import Hub
from control_plane.lease import LeaseConfig, StartRequested
from control_plane.store import Store
from orch_common.manifest import Manifest
from orch_common.wire import StackStatus


def manifest(id_):
    return Manifest.model_validate(
        {
            "id": id_,
            "name": id_.upper(),
            "tagline": f"tag {id_}",
            "compose": "docker-compose.yml",
            "entry": {"service": "web", "port": 80},
            "health": {},
            "expected_boot_s": 10,
        }
    )


class FakeMailer:
    async def send(self, to, subject, body):
        pass


@pytest.fixture
def engine(tmp_path):
    return Engine(
        Store(tmp_path / "o.sqlite"),
        Hub(),
        FakeMailer(),
        {"a": manifest("a"), "b": manifest("b")},
        LeaseConfig(),
        lambda: 100.0,
    )


def client(engine, poll_timeout=0.2):
    app = create_agent_app(engine, clock=lambda: 100.0, poll_timeout=poll_timeout)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent")


def observed(stack_id, status, generation):
    return {"stack_id": stack_id, "status": status, "generation": generation, "at": 1.0}


async def test_desired_returns_current_immediately_if_newer(engine):
    await engine.dispatch(StartRequested("s1", "a", 0.0))
    async with client(engine, poll_timeout=30) as c:
        r = await asyncio.wait_for(c.get("/agent/desired", params={"after_generation": -1}), 2)
    assert r.status_code == 200
    assert r.json() == {"active": "a", "generation": 1}


async def test_desired_long_poll_returns_on_change(engine):
    async with client(engine, poll_timeout=30) as c:
        poll = asyncio.create_task(c.get("/agent/desired", params={"after_generation": 0}))
        await asyncio.sleep(0.05)
        assert not poll.done()
        await engine.dispatch(StartRequested("s1", "a", 0.0))
        r = await asyncio.wait_for(poll, 2)
    assert r.json() == {"active": "a", "generation": 1}


async def test_desired_times_out_with_current_state(engine):
    async with client(engine) as c:
        r = await c.get("/agent/desired", params={"after_generation": 0})
    assert r.json() == {"active": None, "generation": 0}


async def test_desired_requires_after_generation(engine):
    async with client(engine) as c:
        r = await c.get("/agent/desired")
    assert r.status_code == 422


async def test_observed_ready_updates_state(engine):
    await engine.dispatch(StartRequested("s1", "a", 0.0))
    async with client(engine) as c:
        r = await c.post("/agent/observed", json=observed("a", "ready", 1))
    assert r.status_code == 204
    assert engine.state.status == StackStatus.READY
    assert engine.state.lease.window_ends_at is not None


async def test_observed_stale_generation_ignored(engine):
    await engine.dispatch(StartRequested("s1", "a", 0.0))
    async with client(engine) as c:
        r = await c.post("/agent/observed", json=observed("a", "ready", 0))
    assert r.status_code == 204
    assert engine.state.status == StackStatus.STARTING


async def test_observed_stopped_without_stack(engine):
    engine._state = engine.state.__class__(status=StackStatus.STARTING)
    async with client(engine) as c:
        r = await c.post("/agent/observed", json=observed(None, "stopped", 0))
    assert r.status_code == 204
    assert engine.state.status == StackStatus.STOPPED


async def test_agent_api_has_no_manifests_route(engine):
    async with client(engine) as c:
        assert (await c.get("/agent/manifests")).status_code == 404
