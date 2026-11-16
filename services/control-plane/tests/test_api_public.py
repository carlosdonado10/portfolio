import asyncio
import time
from contextlib import asynccontextmanager

import httpx
import pytest
from control_plane.api_public import create_public_app, sse_events
from control_plane.engine import Engine
from control_plane.hub import Hub
from control_plane.lease import LeaseConfig, Observed, StartRequested
from control_plane.ratelimit import TokenBucket
from control_plane.settings import Settings
from control_plane.store import Store
from orch_common.manifest import Manifest
from orch_common.wire import StackStatus


def manifest(id_, hidden=False):
    m = Manifest.model_validate(
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
    m._hidden = hidden
    return m


SECRETS = {"cookie_secret": "s3cret-s3cret-s3cret", "owner_secret": "owner-pw-owner-pw-1"}
MANIFESTS = {"a": manifest("a"), "b": manifest("b"), "secret": manifest("secret", hidden=True)}


class FakeMailer:
    async def send(self, to, subject, body):
        pass


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "o.sqlite")
    hub = Hub()
    clock = Clock()
    eng = Engine(store, hub, FakeMailer(), MANIFESTS, LeaseConfig(), clock)
    settings = Settings(cookie_secure=False, **SECRETS)
    app = create_public_app(eng, store, settings, MANIFESTS, clock)
    return app, eng, store, hub, clock


def client(app, ip=None):
    headers = {"X-Real-IP": ip} if ip else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
    )


@asynccontextmanager
async def visitor(app, ip=None):
    async with client(app, ip) as c:
        await c.get("/api/status")
        yield c


def signed_sid(sid):
    from itsdangerous import URLSafeSerializer

    return URLSafeSerializer("s3cret-s3cret-s3cret", salt="orch-sid").dumps(sid)


def sid_of(c):
    from itsdangerous import URLSafeSerializer

    return URLSafeSerializer("s3cret-s3cret-s3cret", salt="orch-sid").loads(c.cookies["orch_sid"])


async def test_health_ok(env):
    async with client(env[0]) as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_get_mints_cookie(env):
    async with client(env[0]) as c:
        r = await c.get("/api/projects")
        assert "orch_sid" in c.cookies
        assert "httponly" in r.headers["set-cookie"].lower()
        assert "samesite=lax" in r.headers["set-cookie"].lower()
        assert [p["id"] for p in r.json()] == ["a", "b"]
        r2 = await c.get("/api/projects")
        assert "set-cookie" not in r2.headers
        await c.post("/api/activity")  # visits show once the session row exists
    assert env[2].list_sessions()[0]["visits"][0]["path"] == "/api/projects"


async def test_tampered_cookie_is_replaced(env):
    async with client(env[0]) as c:
        c.cookies.set("orch_sid", "forged")
        r = await c.get("/api/status")
        assert "set-cookie" in r.headers


async def test_post_without_cookie_400(env):
    async with client(env[0]) as c:
        r = await c.post("/api/start", json={"stack_id": "a"})
    assert r.status_code == 400
    assert "cookie" in r.json()["detail"]


async def test_start_unknown_404(env):
    async with visitor(env[0]) as c:
        r = await c.post("/api/start", json={"stack_id": "nope"})
    assert r.status_code == 404
    assert "no project" in r.json()["detail"]


async def test_start_hidden_404(env):
    async with visitor(env[0]) as c:
        r = await c.post("/api/start", json={"stack_id": "secret"})
    assert r.status_code == 404


async def test_start_then_status_shows_holder_me(env):
    app, _eng, store, *_ = env
    async with visitor(app) as c:
        r = await c.post("/api/start", json={"stack_id": "a"})
        assert r.status_code == 200
        body = (await c.get("/api/status")).json()
    assert body["active"] == "a"
    assert body["status"] == "starting"
    assert body["me"]["role"] == "holder"
    assert body["me"]["alias"] == body["holder_alias"]
    assert body["window_ends_at"] is None
    assert any(v["path"] == "/api/start" for s in store.list_sessions() for v in s["visits"])


async def test_second_client_queued_with_position_and_me_flag(env):
    app = env[0]
    async with visitor(app) as a, visitor(app) as b:
        await a.post("/api/start", json={"stack_id": "a"})
        r = await b.post("/api/start", json={"stack_id": "b"})
        assert r.status_code == 200
        body = (await b.get("/api/status")).json()
        a_body = (await a.get("/api/status")).json()
    assert body["me"]["role"] == "queued"
    assert body["me"]["position"] == 1
    assert body["me"]["alias"] != body["holder_alias"]
    assert body["queue"] == [{"alias": body["me"]["alias"], "stack_id": "b", "me": True}]
    assert a_body["queue"][0]["me"] is False
    assert a_body["me"]["role"] == "holder"


async def test_gate_only_holder_when_ready(env):
    app, eng, _, _, clock = env
    async with visitor(app) as a, visitor(app) as b:
        await a.post("/api/start", json={"stack_id": "a"})
        assert (await a.get("/internal/gate/a")).status_code == 401
        await eng.dispatch(Observed("a", StackStatus.READY, eng.state.generation, clock()))
        assert (await a.get("/internal/gate/a")).status_code == 204
        assert (await a.get("/internal/gate/b")).status_code == 401
        assert (await b.get("/internal/gate/a")).status_code == 401
    async with client(app) as anon:
        r = await anon.get("/internal/gate/a")
        assert r.status_code == 401
        assert "orch_sid" not in anon.cookies


async def test_stop_by_non_holder_403(env):
    app = env[0]
    async with visitor(app) as a, visitor(app) as b:
        await a.post("/api/start", json={"stack_id": "a"})
        r = await b.post("/api/stop")
        assert r.status_code == 403
        assert r.json()["detail"]
        r = await a.post("/api/stop")
        assert r.status_code == 200
        assert r.json()["me"]["role"] == "none"


async def test_activity_204(env):
    async with visitor(env[0]) as c:
        assert (await c.post("/api/activity")).status_code == 204


async def test_rate_limit_429(env):
    async with visitor(env[0]) as c:
        codes = [(await c.post("/api/start", json={"stack_id": "a"})).status_code for _ in range(6)]
    assert 429 not in codes[:5]
    assert codes[5] == 429


async def test_rate_limit_per_ip(env):
    app = env[0]
    codes = []
    for _ in range(11):
        async with visitor(app, ip="9.9.9.9") as c:
            codes.append((await c.post("/api/start", json={"stack_id": "a"})).status_code)
    assert codes[:10].count(429) == 0
    assert codes[10] == 429


def test_token_bucket_refills():
    tb = TokenBucket(60)
    assert all(tb.allow("k", 0.0) for _ in range(60))
    assert not tb.allow("k", 0.0)
    assert tb.allow("k", 1.0)
    assert not tb.allow("k", 1.0)
    assert tb.allow("other", 1.0)


def test_token_bucket_prunes_full_buckets():
    tb = TokenBucket(60)
    for i in range(10_001):
        tb.allow(f"k{i}", 0.0)
    assert len(tb._buckets) > 0
    tb.allow("late", 100.0)
    assert len(tb._buckets) < 10_001


async def test_email_invalid_422(env):
    async with visitor(env[0]) as c:
        r = await c.post("/api/email", json={"email": "not-an-email"})
    assert r.status_code == 422
    assert "email" in r.json()["detail"]


async def test_email_attaches(env):
    app, eng, store, *_ = env
    async with visitor(app) as a, visitor(app) as b:
        await a.post("/api/start", json={"stack_id": "a"})
        await b.post("/api/start", json={"stack_id": "b"})
        r = await b.post("/api/email", json={"email": "me@example.com"})
        assert r.status_code == 204
        sid = sid_of(b)
    assert store.get_email(sid) == "me@example.com"
    assert eng.state.queue[0].has_email is True


async def test_sse_receives_notification(env):
    _, eng, _, hub, clock = env
    gen = sse_events(eng, hub, "sid-x", clock, ping_s=0.05)

    async def first_data():
        async for frame in gen:
            if frame.startswith("data: "):
                return frame
        return ""

    task = asyncio.create_task(first_data())
    while not hub.connected("sid-x"):
        await asyncio.sleep(0)
    await eng.dispatch(StartRequested("sid-x", "a", clock()))
    frame = await asyncio.wait_for(task, 2)
    await gen.aclose()
    assert '"type": "stack_starting"' in frame
    assert frame.endswith("\n\n")
    assert not hub.connected("sid-x")


async def test_sse_pings_and_marks_seen(env):
    _, eng, _, hub, clock = env
    gen = sse_events(eng, hub, "sid-y", clock, ping_s=0.01)
    assert await asyncio.wait_for(anext(gen), 2) == ": ping\n\n"
    await gen.aclose()
    assert not hub.connected("sid-y")


async def test_sse_route_headers(env):
    app, _, _, hub, _ = env
    # httpx's ASGI transport buffers bodies, so drive the app by hand and
    # stop as soon as the response head has been sent.
    started = asyncio.Event()
    sent = {}

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        if message["type"] == "http.response.start":
            sent.update(message)
            started.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "query_string": b"",
        "headers": [(b"cookie", f"orch_sid={signed_sid('sid-route')}".encode())],
        "client": ("1.2.3.4", 1),
        "server": ("test", 80),
    }
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(started.wait(), 2)
    headers = {k.decode(): v.decode() for k, v in sent["headers"]}
    while not any(hub.connected(sid) for sid in list(hub._subs)):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert sent["status"] == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"
    assert not hub._subs


async def test_admin_requires_secret(env):
    async with client(env[0]) as c:
        for method, path in [
            ("get", "/api/admin/overview"),
            ("post", "/api/admin/force-stop"),
            ("post", "/api/admin/clear-queue"),
        ]:
            assert (await getattr(c, method)(path)).status_code == 401
        assert (await c.post("/api/admin/login", json={"secret": "wrong"})).status_code == 401
    async with client(env[0]) as forger:
        forger.cookies.set("orch_admin", "forged")
        assert (await forger.get("/api/admin/overview")).status_code == 401
    async with client(env[0]) as c:
        r = await c.post("/api/admin/login", json={"secret": "owner-pw-owner-pw-1"})
        assert r.status_code == 200
        o = await c.get("/api/admin/overview")
    assert o.status_code == 200
    assert set(o.json()) == {"state", "sessions", "recent_visits", "observed"}


async def test_admin_force_stop(env):
    app, eng, *_ = env
    async with visitor(app) as a, client(app) as admin:
        await a.post("/api/start", json={"stack_id": "a"})
        await a.get("/api/projects")
        await a.post("/api/email", json={"email": "a@example.com"})
        await admin.post("/api/admin/login", json={"secret": "owner-pw-owner-pw-1"})
        r = await admin.post("/api/admin/force-stop")
        assert r.status_code == 200
        assert eng.state.lease is None
        r = await admin.post("/api/admin/clear-queue")
        assert r.status_code == 200
        o = (await admin.get("/api/admin/overview")).json()
    assert o["sessions"][0]["email"] == "a@example.com"
    assert {v["path"] for v in o["recent_visits"]} == {"/api/start", "/api/projects"}


def test_rejects_short_secrets(env):
    _, eng, store, _, clock = env
    for kwargs in ({"cookie_secret": "short"}, {"owner_secret": "short"}):
        good = Settings(**{**SECRETS, "cookie_secure": False})
        bad = good.model_copy(update=kwargs)
        with pytest.raises(ValueError, match="at least 16"):
            create_public_app(eng, store, bad, MANIFESTS, clock)


async def test_admin_login_empty_secret_rejected(env):
    async with client(env[0]) as c:
        r = await c.post("/api/admin/login", json={"secret": ""})
        assert r.status_code == 401
        assert "orch_admin" not in c.cookies


async def test_health_does_not_mint_or_store(env):
    _, _, store, *_ = env
    async with client(env[0]) as c:
        for _i in range(3):
            r = await c.get("/api/health")
            assert "set-cookie" not in r.headers
    assert store.list_sessions() == []


async def test_get_mint_does_not_write_session_row(env):
    async with client(env[0]) as c:
        await c.get("/api/projects")
        assert "orch_sid" in c.cookies
    assert env[2].list_sessions() == []


async def test_first_post_writes_session_row(env):
    async with visitor(env[0], ip="5.6.7.8") as c:
        assert env[2].list_sessions() == []
        await c.post("/api/activity")
        sid = sid_of(c)
    rows = env[2].list_sessions()
    assert [(r["sid"], r["ip"]) for r in rows] == [(sid, "5.6.7.8")]


async def login(c):
    r = await c.post("/api/admin/login", json={"secret": SECRETS["owner_secret"]})
    assert r.status_code == 200


async def test_admin_cookie_expires(env, monkeypatch):
    real = time.time()
    async with client(env[0]) as c:
        await login(c)
        assert (await c.get("/api/admin/overview")).status_code == 200
        monkeypatch.setattr(time, "time", lambda: real + 13 * 3600)
        assert (await c.get("/api/admin/overview")).status_code == 401


async def test_admin_cookie_revoked_on_secret_rotation(env):
    app, eng, store, _, clock = env
    async with client(app) as c:
        await login(c)
        rotated = Settings(
            cookie_secure=False,
            **{**SECRETS, "owner_secret": "a-different-owner-secret"},
        )
        app2 = create_public_app(eng, store, rotated, MANIFESTS, clock)
        async with client(app2) as c2:
            c2.cookies.set("orch_admin", c.cookies["orch_admin"])
            assert (await c2.get("/api/admin/overview")).status_code == 401
        assert (await c.get("/api/admin/overview")).status_code == 200


async def test_admin_login_rate_limited(env):
    async with client(env[0], ip="7.7.7.7") as c:
        codes = [
            (await c.post("/api/admin/login", json={"secret": "x" * 20})).status_code
            for _ in range(6)
        ]
    assert codes == [401] * 5 + [429]


async def test_sid_cookie_value_not_accepted_as_admin(env):
    async with visitor(env[0]) as c:
        c.cookies.set("orch_admin", c.cookies["orch_sid"])
        assert (await c.get("/api/admin/overview")).status_code == 401


async def test_sse_route_uses_configured_ping_interval(env, monkeypatch):
    _, eng, store, _, clock = env
    seen = {}

    async def fake_events(*args, **kwargs):
        seen.update(kwargs)
        yield ": ping\n\n"

    monkeypatch.setattr("control_plane.api_public.sse_events", fake_events)
    settings = Settings(cookie_secure=False, sse_ping_s=1.5, **SECRETS)
    app = create_public_app(eng, store, settings, MANIFESTS, clock)
    async with visitor(app) as v:
        r = await v.get("/api/events")
    assert r.status_code == 200
    assert seen["ping_s"] == 1.5


# -- final review fixes -------------------------------------------------------


async def test_events_without_cookie_400_and_no_cookie_minted(env):
    async with client(env[0]) as c:
        r = await c.get("/api/events")
    assert r.status_code == 400
    assert "cookie" in r.json()["detail"]
    assert "set-cookie" not in r.headers


async def test_events_with_tampered_cookie_400(env):
    async with client(env[0]) as c:
        c.cookies.set("orch_sid", "forged")
        r = await c.get("/api/events")
    assert r.status_code == 400
    assert "set-cookie" not in r.headers


async def test_leave_queue_removes_me(env):
    app, eng, *_ = env
    async with visitor(app) as a, visitor(app) as b:
        await a.post("/api/start", json={"stack_id": "a"})
        await b.post("/api/start", json={"stack_id": "b"})
        r = await b.post("/api/leave")
        assert r.status_code == 204
        body = (await b.get("/api/status")).json()
    assert body["me"]["role"] == "none"
    assert eng.state.queue == ()
    assert eng.state.lease is not None


async def test_leave_queue_when_not_queued_is_204_noop(env):
    app, eng, *_ = env
    async with visitor(app) as a:
        await a.post("/api/start", json={"stack_id": "a"})
        assert (await a.post("/api/leave")).status_code == 204
    assert eng.state.lease.stack_id == "a"


async def test_leave_without_cookie_400(env):
    async with client(env[0]) as c:
        assert (await c.post("/api/leave")).status_code == 400


async def test_stop_by_non_holder_copy_points_at_leaving(env):
    app = env[0]
    async with visitor(app) as a, visitor(app) as b:
        await a.post("/api/start", json={"stack_id": "a"})
        r = await b.post("/api/stop")
    assert r.status_code == 403
    assert "leave the queue" in r.json()["detail"]


async def test_status_exposes_lease_durations(env):
    async with visitor(env[0]) as c:
        body = (await c.get("/api/status")).json()
    assert body["lease"] == {"window_s": 900, "grace_s": 180, "idle_s": 180}


async def test_projects_visit_not_logged_for_freshly_minted_sid(env):
    _, _, store, *_ = env
    async with client(env[0]) as c:
        await c.get("/api/projects")  # mints: a cookieless hit (bot) is not a visit
        await c.post("/api/activity")
        assert store.list_sessions()[0]["visits"] == []
        await c.get("/api/projects")
    assert [v["path"] for v in store.list_sessions()[0]["visits"]] == ["/api/projects"]


async def test_admin_cookie_scoped_to_admin_api(env):
    async with client(env[0]) as c:
        r = await c.post("/api/admin/login", json={"secret": SECRETS["owner_secret"]})
    cookie = r.headers["set-cookie"]
    assert "Path=/api/admin" in cookie
    assert "Max-Age=43200" in cookie


async def test_admin_logout_deletes_scoped_cookie(env):
    async with client(env[0]) as c:
        await login(c)
        r = await c.post("/api/admin/logout")
        assert r.status_code == 204
        cookie = r.headers["set-cookie"]
        assert "orch_admin=" in cookie
        assert "Path=/api/admin" in cookie
        assert "Max-Age=0" in cookie
        assert (await c.get("/api/admin/overview")).status_code == 401


async def test_admin_overview_includes_observed_reports(env):
    app, eng, _, _, clock = env
    await eng.dispatch(StartRequested("x", "a", clock()))
    await eng.dispatch(
        Observed("a", StackStatus.FAILED, eng.state.generation, clock(), "boot exceeded 5 seconds")
    )
    async with client(app) as c:
        await login(c)
        o = (await c.get("/api/admin/overview")).json()
    assert o["observed"][0]["status"] == "failed"
    assert o["observed"][0]["error"] == "boot exceeded 5 seconds"
    assert o["observed"][0]["stack_id"] == "a"
