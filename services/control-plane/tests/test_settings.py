from control_plane.settings import Settings


def test_settings_reads_nested_lease_env(monkeypatch):
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "c")
    monkeypatch.setenv("ORCH_OWNER_SECRET", "o")
    monkeypatch.setenv("ORCH_LEASE__WINDOW_S", "5")
    settings = Settings()
    assert settings.lease.to_config().window_s == 5
    assert settings.lease.to_config().grace_s == 180
    assert settings.cookie_secure is True
    assert settings.include_hidden is False
    assert settings.public_base_url == ""
