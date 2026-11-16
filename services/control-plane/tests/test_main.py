import httpx
from control_plane.mailer import NullMailer, ResendMailer
from control_plane.main import build
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
        assert (await c.get("/agent/manifests")).json() == ["demo"]
    transport = httpx.ASGITransport(app=public)
    async with httpx.AsyncClient(transport=transport, base_url="http://p") as c:
        assert (await c.get("/api/health")).status_code == 200


def test_build_picks_mailer_from_settings(tmp_path):
    *_, null_engine = build(settings(tmp_path))
    *_, resend_engine = build(settings(tmp_path, resend_api_key="k", email_from="a@b.dev"))
    assert isinstance(null_engine._mailer, NullMailer)
    assert isinstance(resend_engine._mailer, ResendMailer)
