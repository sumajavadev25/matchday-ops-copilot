"""End-to-end API tests via FastAPI's test client (no network, no real model)."""
import io

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def setup_function():
    client.post("/api/reset")  # isolate tests from each other's uploads


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_snapshot_has_seed_zones():
    r = client.get("/api/snapshot")
    assert r.status_code == 200
    assert len(r.json()["zones"]) == 6


def test_triage_endpoint_is_incident_aware():
    r = client.get("/api/triage")
    assert r.status_code == 200
    zones = {z["zone_id"]: z for z in r.json()["zones"]}
    assert len(zones) == 6  # every zone, including normal ones
    # Gate C is 98% AND has a severity-4 medical incident -> critical, not just high.
    assert zones["gate-c"]["risk"] == "critical"
    # Every zone carries a forward projection field (seconds-to-full or null).
    assert all("eta_seconds" in z for z in zones.values())


def test_analyze_returns_recommendations():
    r = client.post("/api/analyze")
    assert r.status_code == 200
    body = r.json()
    assert body["generated_by"] in {"gemini", "fallback"}
    assert len(body["recommendations"]) >= 1
    assert all(rec["reasoning"] for rec in body["recommendations"])


def test_upload_real_data_replaces_snapshot():
    csv = "id,name,capacity,occupancy\nx1,Gate X1,1000,990\nx2,Gate X2,1000,100\n"
    files = {"zones": ("zones.csv", io.BytesIO(csv.encode()), "text/csv")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 200
    assert r.json()["zones_loaded"] == 2
    assert len(client.get("/api/snapshot").json()["zones"]) == 2


def test_upload_bad_csv_rejected():
    csv = "wrong,header\n1,2\n"
    files = {"zones": ("zones.csv", io.BytesIO(csv.encode()), "text/csv")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 400
    assert "details" in r.json()


def test_upload_non_utf8_rejected():
    files = {"zones": ("z.csv", io.BytesIO(b"\xff\xfe\x00bad"), "text/csv")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 400


def test_security_headers_present():
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_triage_lists_open_incidents_only():
    inc = client.get("/api/triage").json()["incidents"]
    ids = {i["id"] for i in inc}
    assert "inc-1" in ids            # open medical incident is listed
    assert all(i["severity"] >= 1 for i in inc)
    # zone id is resolved to a human name for display
    assert any(i["zone"] == "Gate C" for i in inc)


def test_csp_header_present():
    r = client.get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_rate_limiter_allows_then_blocks():
    from app.main import RateLimiter
    rl = RateLimiter(limit=2, window=10)
    assert rl.allow("ip", 0) is True
    assert rl.allow("ip", 1) is True
    assert rl.allow("ip", 2) is False    # third within window blocked
    assert rl.allow("ip", 11) is True     # fresh window resets


def test_ask_without_key_is_graceful():
    # conftest disables the key, so the copilot answers that it needs one.
    r = client.post("/api/ask", json={"question": "what's my priority?"})
    assert r.status_code == 200
    assert r.json()["generated_by"] == "unavailable"


def test_ask_rejects_empty_question():
    r = client.post("/api/ask", json={"question": ""})
    assert r.status_code == 422  # pydantic min_length


def test_ask_answers_with_copilot(monkeypatch):
    from app import main as m
    monkeypatch.setattr(m.settings, "gemini_api_key", "test-key")  # enable genai
    monkeypatch.setattr(m, "answer_question",
                        lambda q, snap, etas: "Redirect arrivals to Gate D.")
    r = client.post("/api/ask", json={"question": "what if I close Gate B?"})
    assert r.status_code == 200
    assert r.json() == {"answer": "Redirect arrivals to Gate D.", "generated_by": "gemini"}


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Ops Copilot" in r.text
