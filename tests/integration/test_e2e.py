"""End-to-end: the real compose stack, the nginx gateway and the two example projects.

Needs a Docker daemon (`make e2e`). The module fixture builds and starts everything with short
lease timings, and removes it again (containers, the sqlite volume, the temp manifest).
"""

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
TEMP_DIR = PROJECTS / "_e2e"
HTTP_PORT = os.environ.get("HTTP_PORT", "8080")
BASE = f"http://localhost:{HTTP_PORT}"
ADMIN_LOGIN = "example-owner-value-for-e2e"
WINDOW_S, GRACE_S = 5, 3

MAKE_VARS = {
    "ORCH_PROJECTS_DIR": str(PROJECTS),
    "ORCH_INCLUDE_HIDDEN": "1",
    "ORCH_COOKIE_SECRET": "example-cookie-value-for-e2e",
    "ORCH_OWNER_SECRET": ADMIN_LOGIN,
    "ORCH_COOKIE_SECURE": "false",
    "HTTP_PORT": HTTP_PORT,
    "ORCH_LEASE__WINDOW_S": str(WINDOW_S),
    "ORCH_LEASE__GRACE_S": str(GRACE_S),
    "ORCH_LEASE__IDLE_S": "3",
    "ORCH_LEASE__PRESENCE_S": "3",
    "ORCH_SSE_PING_S": "1",
}

BROKEN_MANIFEST = """\
id = "broken"
name = "Broken example"
compose = "docker-compose.yml"
entry = { service = "web", port = 8000 }
health = { path = "/healthz", timeout_s = 5, interval_s = 1 }
expected_boot_s = 5
order = 3
"""

BROKEN_COMPOSE = """\
services:
  web:
    build: ../_examples/fast
    image: orch-example-broken:local
    environment:
      PROJECT_ID: broken
      READY_AFTER_S: "999"
    networks:
      orch-stacks:
        aliases: [broken-entry]

networks:
  orch-stacks:
    external: true
"""


def make(*targets: str, **overrides: str) -> None:
    args = [f"{k}={v}" for k, v in {**MAKE_VARS, **overrides}.items()]
    subprocess.run(["make", *targets, *args], cwd=ROOT, check=True)


def compose_projects() -> list[str]:
    out = subprocess.run(
        ["docker", "compose", "ls", "--all", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [p["Name"] for p in json.loads(out or "[]")]


def wait_for(check: Callable[[], Any], timeout: float, what: str, every: float = 0.3) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(every)


def status(client: httpx.Client) -> dict[str, Any]:
    r = client.get("/api/status")
    r.raise_for_status()
    body: dict[str, Any] = r.json()
    return body


def is_holder_ready(client: httpx.Client, stack_id: str) -> Callable[[], bool]:
    def check() -> bool:
        s = status(client)
        ok = s["me"]["role"] == "holder" and s["active"] == stack_id and s["status"] == "ready"
        return bool(ok)

    return check


def start(client: httpx.Client, stack_id: str) -> None:
    status(client)  # mints the session cookie
    r = client.post("/api/start", json={"stack_id": stack_id})
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module", autouse=True)
def platform() -> Iterator[None]:
    if os.environ.get("ORCH_E2E") != "1":
        pytest.exit(
            "refusing to run: this test wipes the portfolio-platform_orch-data volume and "
            "tears down every orch-* stack. Run it with `make e2e` (sets ORCH_E2E=1).",
            returncode=2,
        )
    if shutil.which("docker") is None:
        pytest.fail("docker is required for the e2e test")
    TEMP_DIR.joinpath("broken").mkdir(parents=True, exist_ok=True)
    (TEMP_DIR / "broken" / "stack.toml").write_text(BROKEN_MANIFEST)
    (TEMP_DIR / "broken" / "docker-compose.yml").write_text(BROKEN_COMPOSE)

    def teardown() -> None:
        subprocess.run(["make", "down", *[f"{k}={v}" for k, v in MAKE_VARS.items()]], cwd=ROOT)
        subprocess.run(
            ["docker", "volume", "rm", "-f", "portfolio-platform_orch-data"],
            capture_output=True,
        )

    teardown()  # a clean slate, including the sqlite volume
    try:
        make("render", "prepare", "up")
        wait_for(lambda: _proxy_up(), 120, "gateway health", every=1)
        yield
    finally:
        teardown()
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        make("render", ORCH_INCLUDE_HIDDEN="0")  # drop the temp project's routes


def _proxy_up() -> bool:
    try:
        return httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200
    except httpx.TransportError:
        return False


@pytest.fixture(scope="module")
def admin() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE) as client:
        r = client.post("/api/admin/login", json={"secret": ADMIN_LOGIN})
        assert r.status_code == 200, r.text
        yield client


@pytest.fixture(autouse=True)
def reset(admin: httpx.Client) -> None:
    """Every test starts with an empty box: no holder, no queue, nothing running."""
    assert admin.post("/api/admin/force-stop").status_code == 200
    assert admin.post("/api/admin/clear-queue").status_code == 200

    def idle() -> bool:
        s = status(admin)
        return s["active"] is None and not s["queue"] and s["status"] in {"stopped", "failed"}

    wait_for(idle, 30, "an idle box")
    wait_for(lambda: not [p for p in compose_projects() if p.startswith("orch-")], 30, "no stacks")


@pytest.fixture
def a() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE) as client:
        yield client


@pytest.fixture
def b() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE) as client:
        yield client


def test_gate_redirects_before_ready(a: httpx.Client) -> None:
    r = a.get("/p/fast/")
    assert r.status_code == 302
    assert r.headers["location"] == "/lab/p/fast"


def test_holder_reaches_stack_with_injected_script(a: httpx.Client, b: httpx.Client) -> None:
    start(a, "fast")
    wait_for(is_holder_ready(a, "fast"), 15, "fast to be ready for A")
    status(b)
    page = a.get("/p/fast/")
    assert page.status_code == 200
    assert "/lab/notify.js" in page.text
    assert b.get("/p/fast/").status_code == 302


def test_handoff_to_queued_visitor(a: httpx.Client, b: httpx.Client) -> None:
    start(a, "fast")
    wait_for(is_holder_ready(a, "fast"), 15, "fast to be ready for A")
    status(b)
    # An email keeps B's queue entry valid without an open event stream.
    assert b.post("/api/email", json={"email": "b@example.com"}).status_code == 204
    start(b, "slow")
    assert status(b)["me"]["role"] == "queued"

    wait_for(is_holder_ready(b, "slow"), WINDOW_S + GRACE_S + 25, "handoff to B, slow ready")
    assert "orch-fast" not in compose_projects()
    assert a.get("/p/fast/").status_code == 302
    assert b.get("/p/slow/").status_code == 200


def test_boot_timeout_fails_and_releases(a: httpx.Client) -> None:
    start(a, "broken")
    seen: set[str] = set()

    def released_after_failure() -> bool:
        s = status(a)
        seen.add(s["status"])
        return "failed" in seen and s["active"] is None and s["me"]["role"] == "none"

    wait_for(released_after_failure, 30, "failure, then the lease released", every=0.2)
    assert "failed" in seen


def test_internal_paths_not_public(a: httpx.Client) -> None:
    assert a.get("/internal/gate/fast").status_code == 404
    assert a.get("/agent/desired").status_code == 404


def test_sse_disconnect_releases_subscription(a: httpx.Client, b: httpx.Client) -> None:
    """An open event stream keeps a queue entry present; closing it lets the entry lapse.

    B has no email, so presence is all that keeps its entry alive (PRESENCE_S=3). The stream
    pings every second (SSE_PING_S=1), each ping refreshing presence. A boots `slow` (20s, no
    protected window until ready) and stays active, so nothing can hand off while B waits.
    With the stream open B must outlive three presence periods; after it closes, B must lapse
    within presence + about 2s.
    """
    presence_s = int(MAKE_VARS["ORCH_LEASE__PRESENCE_S"])
    start(a, "slow")
    status(b)
    start(b, "fast")
    assert status(b)["me"]["role"] == "queued"

    with b.stream("GET", "/api/events", timeout=httpx.Timeout(10, read=None)) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        end = time.monotonic() + 3 * presence_s + 1
        while time.monotonic() < end:
            a.post("/api/activity")
            assert status(b)["me"]["role"] == "queued", "the open stream should keep B present"
            time.sleep(0.5)
    closed_at = time.monotonic()

    def dropped() -> bool:
        a.post("/api/activity")
        s = status(b)
        return bool(s["me"]["role"] == "none" and not s["queue"])

    wait_for(dropped, presence_s + 3, "B's entry to lapse after the stream closed", every=0.3)
    assert time.monotonic() - closed_at <= presence_s + 3
    assert status(a)["me"]["role"] == "holder"
