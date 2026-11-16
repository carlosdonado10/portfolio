"""Public HTTP API: anonymous sessions, lease actions, SSE, nginx gate, owner admin."""

import asyncio
import contextlib
import json
import secrets
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from itsdangerous import BadSignature, URLSafeSerializer
from orch_common.manifest import Manifest
from orch_common.wire import StackStatus
from pydantic import BaseModel, EmailStr

from control_plane.engine import Engine
from control_plane.hub import Hub
from control_plane.lease import (
    Activity,
    AdminClearQueue,
    AdminForceStop,
    EmailAttached,
    Rejected,
    Seen,
    StartRequested,
    State,
    StopRequested,
)
from control_plane.ratelimit import TokenBucket
from control_plane.settings import Settings
from control_plane.store import Store

SID_COOKIE = "orch_sid"
ADMIN_COOKIE = "orch_admin"
COOKIE_MAX_AGE = 30 * 24 * 3600

NO_COOKIE = (
    "We use one anonymous cookie to hold your place in line. There's no account "
    "and nothing else is tracked. Please enable cookies for this site and reload."
)
NOT_FOUND = "There's no project with that id, so there is nothing to start."
RATE_LIMITED = (
    "Too many requests, please slow down. The box only runs one project at a "
    "time anyway, so there's nothing to gain by retrying quickly."
)
BAD_EMAIL = (
    "That doesn't look like a valid email address. It's only used to tell you "
    "when your turn comes up or your project is ready."
)
BAD_REQUEST = "That request was malformed. Check the fields and try again."
ADMIN_REQUIRED = "This area is for the site owner and needs the owner secret."
LOGIN_REJECTED = "That secret isn't right."


class StartBody(BaseModel):
    stack_id: str


class EmailBody(BaseModel):
    email: EmailStr


class LoginBody(BaseModel):
    secret: str


def _sse_data(msg: dict[str, Any]) -> str:
    return f"data: {json.dumps(msg)}\n\n"


async def sse_events(
    engine: Engine,
    hub: Hub,
    sid: str,
    clock: Callable[[], float] = time.time,
    ping_s: float = 15.0,
) -> AsyncGenerator[str]:
    """SSE frames for one session; closing the generator releases the subscription."""
    async with hub.subscribe(sid) as sub:
        await engine.dispatch(Seen(sid, clock()))
        pending: asyncio.Future[dict[str, Any]] = asyncio.ensure_future(anext(sub))
        try:
            while True:
                done, _ = await asyncio.wait({pending}, timeout=ping_s)
                if done:
                    msg = pending.result()
                    pending = asyncio.ensure_future(anext(sub))
                    yield _sse_data(msg)
                else:
                    await engine.dispatch(Seen(sid, clock()))
                    yield ": ping\n\n"
        finally:
            # Must be fully stopped before the hub closes the message generator.
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending


def create_public_app(
    engine: Engine,
    store: Store,
    settings: Settings,
    manifests: dict[str, Manifest] | None = None,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    app = FastAPI(title="Portfolio Control Plane", version="0.1.0")
    catalog = manifests if manifests is not None else engine.manifests
    visible = {k: m for k, m in catalog.items() if settings.include_hidden or not m.hidden}
    sid_signer = URLSafeSerializer(settings.cookie_secret, salt="orch-sid")
    admin_signer = URLSafeSerializer(settings.cookie_secret, salt="orch-admin")
    ip_limit = TokenBucket(10)
    sid_limit = TokenBucket(5)

    def client_ip(request: Request) -> str:
        real = request.headers.get("x-real-ip")
        if real:
            return real
        return request.client.host if request.client else "unknown"

    def read_sid(request: Request) -> str | None:
        raw = request.cookies.get(SID_COOKIE)
        if not raw:
            return None
        try:
            value = sid_signer.loads(raw)
        except BadSignature:
            return None
        return value if isinstance(value, str) and value else None

    def is_admin(request: Request) -> bool:
        raw = request.cookies.get(ADMIN_COOKIE)
        if not raw:
            return False
        try:
            return bool(admin_signer.loads(raw) == "owner")
        except BadSignature:
            return False

    def err(status: int, detail: str) -> JSONResponse:
        return JSONResponse({"detail": detail}, status_code=status)

    @app.exception_handler(Rejected)
    async def _rejected(_: Request, exc: Rejected) -> JSONResponse:
        return err(exc.status, exc.reason)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        is_email = any("email" in err_["loc"] for err_ in exc.errors())
        return err(422, BAD_EMAIL if is_email else BAD_REQUEST)

    @app.middleware("http")
    async def session_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        sid = read_sid(request)
        minted = False
        if path.startswith("/internal/"):
            pass  # the gate only reads the cookie, it never mints one
        elif sid is None and request.method == "GET":
            sid = secrets.token_urlsafe(24)
            store.ensure_session(sid, client_ip(request))
            minted = True
        elif sid is None and request.method == "POST" and not path.startswith("/api/admin/"):
            return err(400, NO_COOKIE)
        request.state.sid = sid
        response = await call_next(request)
        if minted and sid is not None:
            response.set_cookie(
                SID_COOKIE,
                sid_signer.dumps(sid),
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=settings.cookie_secure,
                path="/",
            )
        return response

    def status_body(state: State, sid: str | None) -> dict[str, Any]:
        lease = state.lease
        queue = [
            {"alias": q.alias, "stack_id": q.stack_id, "me": q.sid == sid} for q in state.queue
        ]
        role, position, alias = "none", None, None
        if lease is not None and lease.sid == sid:
            role, alias = "holder", lease.alias
        else:
            for i, q in enumerate(state.queue):
                if q.sid == sid:
                    role, position, alias = "queued", i + 1, q.alias
                    break
        return {
            "active": lease.stack_id if lease else None,
            "status": state.status.value,
            "holder_alias": lease.alias if lease else None,
            "window_ends_at": lease.window_ends_at if lease else None,
            "grace_deadline": lease.grace_deadline if lease else None,
            "queue": queue,
            "me": {"role": role, "position": position, "alias": alias},
        }

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/projects")
    async def projects(request: Request) -> list[dict[str, Any]]:
        store.log_visit(request.state.sid, "/api/projects", clock())
        return [
            {
                "id": m.id,
                "name": m.name,
                "tagline": m.tagline,
                "base_path": m.base_path,
                "expected_boot_s": m.expected_boot_s,
                "demo_url": m.demo_url,
            }
            for m in visible.values()
        ]

    @app.get("/api/status")
    async def status(request: Request) -> dict[str, Any]:
        return status_body(engine.state, request.state.sid)

    @app.post("/api/start")
    async def start(request: Request, body: StartBody) -> Response:
        sid: str = request.state.sid
        now = clock()
        if not (ip_limit.allow(client_ip(request), now) and sid_limit.allow(sid, now)):
            return err(429, RATE_LIMITED)
        if body.stack_id not in visible:
            return err(404, NOT_FOUND)
        store.log_visit(sid, "/api/start", now)
        state = await engine.dispatch(
            StartRequested(sid, body.stack_id, now, store.get_email(sid) is not None)
        )
        return JSONResponse(status_body(state, sid))

    @app.post("/api/stop")
    async def stop(request: Request) -> dict[str, Any]:
        sid: str = request.state.sid
        state = await engine.dispatch(StopRequested(sid, clock()))
        return status_body(state, sid)

    @app.post("/api/activity", status_code=204)
    async def activity(request: Request) -> Response:
        await engine.dispatch(Activity(request.state.sid, clock()))
        return Response(status_code=204)

    @app.post("/api/email", status_code=204)
    async def email(request: Request, body: EmailBody) -> Response:
        sid: str = request.state.sid
        store.set_email(sid, str(body.email))
        await engine.dispatch(EmailAttached(sid, clock()))
        return Response(status_code=204)

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        return StreamingResponse(
            sse_events(engine, engine.hub, request.state.sid, clock),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/internal/gate/{stack_id}")
    async def gate(stack_id: str, request: Request) -> Response:
        state = engine.state
        sid = request.state.sid
        lease = state.lease
        ok = (
            sid is not None
            and lease is not None
            and lease.stack_id == stack_id
            and state.status == StackStatus.READY
            and secrets.compare_digest(lease.sid, sid)
        )
        return Response(status_code=204 if ok else 401)

    # -- owner admin ---------------------------------------------------------

    @app.post("/api/admin/login")
    async def admin_login(body: LoginBody) -> Response:
        if not secrets.compare_digest(body.secret.encode(), settings.owner_secret.encode()):
            return err(401, LOGIN_REJECTED)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            ADMIN_COOKIE,
            admin_signer.dumps("owner"),
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            path="/",
        )
        return response

    @app.post("/api/admin/force-stop")
    async def admin_force_stop(request: Request) -> Response:
        if not is_admin(request):
            return err(401, ADMIN_REQUIRED)
        state = await engine.dispatch(AdminForceStop(clock()))
        return JSONResponse(status_body(state, None))

    @app.post("/api/admin/clear-queue")
    async def admin_clear_queue(request: Request) -> Response:
        if not is_admin(request):
            return err(401, ADMIN_REQUIRED)
        state = await engine.dispatch(AdminClearQueue(clock()))
        return JSONResponse(status_body(state, None))

    @app.get("/api/admin/overview")
    async def admin_overview(request: Request) -> Response:
        if not is_admin(request):
            return err(401, ADMIN_REQUIRED)
        sessions = store.list_sessions()
        visits = sorted(
            ({"sid": s["sid"], **v} for s in sessions for v in s["visits"]),
            key=lambda v: v["at"],
            reverse=True,
        )[:100]
        return JSONResponse(
            {
                "state": json.loads(engine.state.to_json()),
                "sessions": [
                    {k: s[k] for k in ("sid", "email", "ip", "created_at")} for s in sessions
                ],
                "recent_visits": visits,
            }
        )

    return app
