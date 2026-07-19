"""Configuration parsing: env-driven, with a clamped/guarded threshold."""
from app.config import Settings


def test_defaults_when_env_unset(monkeypatch):
    for var in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FALLBACK_MODEL",
                "CROWD_ALERT_THRESHOLD"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.gemini_api_key == ""
    assert s.gemini_model == "gemini-flash-latest"
    assert s.gemini_fallback_model == "gemini-flash-lite-latest"
    assert s.crowd_alert_threshold == 0.80
    assert s.genai_enabled is False


def test_genai_enabled_when_key_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc123")
    assert Settings().genai_enabled is True


def test_threshold_clamped_to_upper_bound(monkeypatch):
    monkeypatch.setenv("CROWD_ALERT_THRESHOLD", "5.0")
    assert Settings().crowd_alert_threshold == 1.0


def test_threshold_clamped_to_lower_bound(monkeypatch):
    monkeypatch.setenv("CROWD_ALERT_THRESHOLD", "-3")
    assert Settings().crowd_alert_threshold == 0.1


def test_threshold_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CROWD_ALERT_THRESHOLD", "not-a-number")
    assert Settings().crowd_alert_threshold == 0.80


def test_custom_model_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-pro")
    assert Settings().gemini_model == "gemini-3-pro"
