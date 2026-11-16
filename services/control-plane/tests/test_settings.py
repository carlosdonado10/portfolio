import pytest
from control_plane.settings import Settings
from pydantic import ValidationError


def test_settings_reads_nested_lease_env(monkeypatch):
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "c" * 16)
    monkeypatch.setenv("ORCH_OWNER_SECRET", "o" * 16)
    monkeypatch.setenv("ORCH_LEASE__WINDOW_S", "5")
    settings = Settings()
    assert settings.lease.to_config().window_s == 5
    assert settings.lease.to_config().grace_s == 180
    assert settings.cookie_secure is True
    assert settings.include_hidden is False
    assert settings.public_base_url == ""


def test_sse_ping_defaults_and_reads_env(monkeypatch):
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "c" * 16)
    monkeypatch.setenv("ORCH_OWNER_SECRET", "o" * 16)
    assert Settings().sse_ping_s == 15.0
    monkeypatch.setenv("ORCH_SSE_PING_S", "1")
    assert Settings().sse_ping_s == 1.0


def test_rejects_short_secrets(monkeypatch):
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "c" * 16)
    monkeypatch.setenv("ORCH_OWNER_SECRET", "short")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("ORCH_OWNER_SECRET", "o" * 16)
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "")
    with pytest.raises(ValidationError):
        Settings()


def test_boot_watchdog_defaults_and_reads_env(monkeypatch):
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "c" * 16)
    monkeypatch.setenv("ORCH_OWNER_SECRET", "o" * 16)
    assert Settings().lease.to_config().boot_watchdog_s == 900
    monkeypatch.setenv("ORCH_LEASE__BOOT_WATCHDOG_S", "60")
    assert Settings().lease.to_config().boot_watchdog_s == 60


def test_repos_dir_is_not_a_control_plane_setting():
    assert "repos_dir" not in Settings.model_fields
