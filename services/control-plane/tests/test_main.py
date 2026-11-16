import asyncio

import httpx
import pytest
from control_plane.mailer import NullMailer, ResendMailer
from control_plane.main import build, make_server, run
from control_plane.settings import Settings

SECRETS = {"cookie_secret": "c" * 20, "owner_secret": "o" * 20}


def settings(tmp_path, **kw):
    projects = tmp_path / "projects" / "demo"
    projects.mkdir(parents=True, exist_ok=True)
    (projects / "docker-compose.yml").write_text("services: {}\n")
    (projects / "stack.toml").write_text(
        'id = "demo"\nname = "Demo"\ntagline = "t"\ncompose = "docker-compose.yml"\n'
        'expected_boot_s = 5\n[entry]\nservice = "web"\nport = 80\n[health]\n'
    )
    return Settings(
        db_path=tmp_path / "o.sqlite", projects_dir=tmp_path / "projects", **SECRETS, **kw
    )


async def test_build_wires_both_apps_over_one_engine(tmp_path):
    public, agent, engine = build(settings(tmp_path))
    assert list(engine.manifests) == ["demo"]
    transport = httpx.ASGITransport(app=agent)
    async with httpx.AsyncClient(transport=transport, base_url="http://a") as c:
        assert (await c.get("/agent/desired", params={"after_generation": -1})).json() == {
            "active": None,
            "generation": 0,
        }
    transport = httpx.ASGITransport(app=public)
    async with httpx.AsyncClient(transport=transport, base_url="http://p") as c:
        assert (await c.get("/api/health")).status_code == 200


def test_build_picks_mailer_from_settings(tmp_path):
    *_, null_engine = build(settings(tmp_path))
    *_, resend_engine = build(settings(tmp_path, resend_api_key="k", email_from="a@b.dev"))
    assert isinstance(null_engine._mailer, NullMailer)
    assert isinstance(resend_engine._mailer, ResendMailer)


class FakeServer:
    def __init__(self, behaviour="block"):
        self.should_exit = False
        self.behaviour = behaviour

    async def serve(self):
        if self.behaviour == "return":
            return
        if self.behaviour == "exit":
            raise SystemExit(1)
        while not self.should_exit:
            await asyncio.sleep(0.01)


async def forever():
    await asyncio.sleep(3600)


async def crash():
    raise RuntimeError("tick boom")


async def test_serve_exits_nonzero_when_ticker_crashes():
    servers = [FakeServer(), FakeServer()]
    code = await asyncio.wait_for(run(servers, crash(), asyncio.Event()), 2)
    assert code == 1
    assert all(s.should_exit for s in servers)


@pytest.mark.parametrize("behaviour", ["return", "exit"])
async def test_serve_exits_nonzero_when_a_server_returns(behaviour):
    servers = [FakeServer(behaviour), FakeServer()]
    code = await asyncio.wait_for(run(servers, forever(), asyncio.Event()), 2)
    assert code == 1
    assert servers[1].should_exit


async def test_serve_shutdown_signal_stops_everything_cleanly():
    servers = [FakeServer(), FakeServer()]
    stop = asyncio.Event()
    task = asyncio.create_task(run(servers, forever(), stop))
    await asyncio.sleep(0.05)
    assert not task.done()
    stop.set()
    assert await asyncio.wait_for(task, 2) == 0
    assert all(s.should_exit for s in servers)


def test_server_config_bounds_graceful_shutdown(tmp_path):
    public, _, engine = build(settings(tmp_path))
    server = make_server(public, 8000)
    assert server.config.timeout_graceful_shutdown == 5
    assert server.config.proxy_headers is False
    engine.close()
