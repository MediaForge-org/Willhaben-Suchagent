from agent.app.core.config import Settings


def test_ntfy_settings_accept_documented_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("NTFY_ENABLED", "true")
    monkeypatch.setenv("NTFY_BASE_URL", "https://ntfy.example.test")
    monkeypatch.setenv("NTFY_TOPIC", "my-topic")
    monkeypatch.setenv("NTFY_TOKEN", "private-token")
    monkeypatch.setenv("NTFY_TIMEOUT", "4.5")

    settings = Settings(_env_file=None)

    assert settings.ntfy_enabled is True
    assert settings.ntfy_base_url == "https://ntfy.example.test"
    assert settings.ntfy_topic == "my-topic"
    assert settings.ntfy_token is not None
    assert settings.ntfy_token.get_secret_value() == "private-token"
    assert settings.ntfy_timeout_seconds == 4.5
    assert "private-token" not in repr(settings)


def test_desktop_sound_defaults_on_and_accepts_environment_override(monkeypatch) -> None:
    assert Settings(_env_file=None).desktop_sound_enabled is True
    assert Settings(_env_file=None).desktop_sound_id == "notify"

    monkeypatch.setenv("WILLHABEN_DESKTOP_SOUND_ENABLED", "false")

    assert Settings(_env_file=None).desktop_sound_enabled is False
