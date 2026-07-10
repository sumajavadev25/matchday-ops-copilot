"""Triage logic — deterministic, so fully assertable without any model calls."""
import app.copilot as copilot
from app.config import settings
from app.copilot import assess_zone, build_report, triage
from app.models import Incident, IncidentType, RiskLevel, StadiumSnapshot, Zone

T = 0.80


def z(occ, cap=1000, id="z"):
    return Zone(id=id, name=id.upper(), capacity=cap, occupancy=occ)


def test_normal_zone():
    assert assess_zone(z(500), [], T) == RiskLevel.NORMAL


def test_high_at_threshold():
    assert assess_zone(z(800), [], T) == RiskLevel.HIGH


def test_critical_at_capacity():
    assert assess_zone(z(1000), [], T) == RiskLevel.CRITICAL


def test_critical_over_capacity():
    assert assess_zone(z(1200), [], T) == RiskLevel.CRITICAL


def test_high_severity_incident_escalates_quiet_zone():
    # A calm zone (10% full) with a severity-4 incident is still CRITICAL.
    inc = [Incident(id="i", type=IncidentType.MEDICAL, zone_id="z", severity=4)]
    assert assess_zone(z(100), inc, T) == RiskLevel.CRITICAL


def test_resolved_incident_does_not_escalate():
    inc = [Incident(id="i", type=IncidentType.MEDICAL, zone_id="z", severity=5, resolved=True)]
    assert assess_zone(z(100), inc, T) == RiskLevel.NORMAL


def test_incident_for_other_zone_ignored():
    inc = [Incident(id="i", type=IncidentType.SECURITY, zone_id="other", severity=5)]
    assert assess_zone(z(100), inc, T) == RiskLevel.NORMAL


def test_zero_capacity_zone_with_people_is_critical():
    assert assess_zone(z(10, cap=0), [], T) == RiskLevel.CRITICAL


def test_triage_orders_critical_first():
    snap = StadiumSnapshot(zones=[z(820, id="a"), z(1000, id="b"), z(500, id="c")])
    ordered = triage(snap, T)
    assert [zone.id for zone, _ in ordered] == ["b", "a"]  # c is normal, dropped


def test_zone_risks_covers_every_zone_including_normal():
    snap = StadiumSnapshot(zones=[z(1000, id="a"), z(500, id="b")])
    risks = copilot.zone_risks(snap, threshold=T)
    assert len(risks) == 2  # normal zones included, unlike triage()
    by_id = {zone.id: r for zone, r in risks}
    assert by_id["a"] == RiskLevel.CRITICAL and by_id["b"] == RiskLevel.NORMAL


def test_prompt_encodes_register_guidance():
    snap = StadiumSnapshot(zones=[z(1000, id="a")])
    prompt = copilot._build_prompt([(snap.zones[0], RiskLevel.CRITICAL, None)], snap, ["en"])
    assert "register" in prompt.lower()
    assert "medical" in prompt.lower()


def test_build_report_empty_snapshot():
    rep = build_report(StadiumSnapshot(), threshold=T)
    assert rep.recommendations == []
    assert rep.generated_by == "none"


def test_build_report_no_key_uses_fallback():
    # With GenAI disabled (see conftest), the report must still build.
    snap = StadiumSnapshot(zones=[z(1000, id="a")])
    rep = build_report(snap, threshold=T)
    assert rep.generated_by == "fallback"
    assert len(rep.recommendations) == 1
    assert rep.recommendations[0].reasoning  # explanation is always present
    assert rep.recommendations[0].announcements.get("en")


def test_build_report_uses_gemini_output_when_available(monkeypatch):
    # Simulate a configured key + a successful model call (no real network).
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(copilot, "generate_reasoning", lambda items, snap, langs: {
        "a": {"zone_id": "a", "headline": "H", "reasoning": "R", "action": "A",
              "announcements": {"en": "hi", "es": "hola", "fr": "salut"}},
    })
    rep = build_report(StadiumSnapshot(zones=[z(1000, id="a")]), threshold=T)
    assert rep.generated_by == "gemini"
    assert rep.recommendations[0].announcements == {"en": "hi", "es": "hola", "fr": "salut"}


def test_build_report_falls_back_when_gemini_errors(monkeypatch):
    # A model failure must degrade gracefully, never crash the control room.
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    def boom(items, snap, langs):
        raise RuntimeError("model down")

    monkeypatch.setattr(copilot, "generate_reasoning", boom)
    rep = build_report(StadiumSnapshot(zones=[z(1000, id="a")]), threshold=T)
    assert rep.generated_by == "fallback"
    assert rep.recommendations[0].reasoning  # fallback still explains itself


def test_generate_reasoning_retries_on_server_error(monkeypatch):
    # Transient 503s should be retried, not surfaced on the first failure.
    from google.genai import errors

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(copilot, "_RETRY_BACKOFF", 0)  # no real sleeping in tests

    calls = {"n": 0}

    class FakeResp:
        text = '[{"zone_id": "a", "headline": "h", "reasoning": "r", "action": "x"}]'

    class FakeModels:
        def generate_content(self, **kwargs):
            calls["n"] += 1
            if calls["n"] < 2:
                raise errors.ServerError(503, {"error": {"message": "busy"}})
            return FakeResp()

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", FakeClient)

    snap = StadiumSnapshot(zones=[z(1000, id="a")])
    out = copilot.generate_reasoning([(snap.zones[0], RiskLevel.CRITICAL, None)], snap, ["en"])
    assert calls["n"] == 2  # failed once, succeeded on retry
    assert out["a"]["reasoning"] == "r"


def test_generate_reasoning_falls_over_to_second_model(monkeypatch):
    # Primary model rate-limited (429) -> switch to the fallback model, which works.
    from google.genai import errors

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "primary")
    monkeypatch.setattr(settings, "gemini_fallback_model", "backup")
    seen = []

    class FakeResp:
        text = '[{"zone_id": "a", "headline": "h", "reasoning": "r", "action": "x"}]'

    class FakeModels:
        def generate_content(self, *, model, contents, config=None):
            seen.append(model)
            if model == "primary":
                raise errors.ClientError(429, {"error": {"message": "quota"}})
            return FakeResp()

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", FakeClient)

    snap = StadiumSnapshot(zones=[z(1000, id="a")])
    out = copilot.generate_reasoning([(snap.zones[0], RiskLevel.CRITICAL, None)], snap, ["en"])
    assert seen == ["primary", "backup"]  # tried primary, then fell over
    assert out["a"]["reasoning"] == "r"


def test_generate_reasoning_parses_structured_output(monkeypatch):
    # Simulate the SDK's structured-output path: resp.parsed holds objects,
    # announcements arrive as a list and must fold into a {lang: text} dict.
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    class Rec:
        def model_dump(self):
            return {"zone_id": "a", "headline": "h", "reasoning": "r", "action": "x",
                    "announcements": [{"lang": "en", "text": "hi"},
                                      {"lang": "es", "text": "hola"}]}

    class FakeResp:
        parsed = [Rec()]
        text = "unused when parsed is present"

    class FakeModels:
        def generate_content(self, *, model, contents, config=None):
            return FakeResp()

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", FakeClient)

    snap = StadiumSnapshot(zones=[z(1000, id="a")])
    out = copilot.generate_reasoning(
        [(snap.zones[0], RiskLevel.CRITICAL, None)], snap, ["en", "es"])
    assert out["a"]["announcements"] == {"en": "hi", "es": "hola"}


def test_prompt_includes_few_shot_examples():
    snap = StadiumSnapshot(zones=[z(1000, id="a")])
    prompt = copilot._build_prompt([(snap.zones[0], RiskLevel.CRITICAL, None)], snap, ["en"])
    assert "Examples of the expected voice" in prompt
    assert "never" in prompt.lower() and "emergency" in prompt.lower()
