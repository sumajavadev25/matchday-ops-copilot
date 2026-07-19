"""FastAPI surface for the MatchDay Ops Copilot.

Endpoints:
  GET  /                 accessible control-room dashboard
  GET  /api/health       liveness + whether GenAI is configured
  GET  /api/snapshot     current (live-advancing) stadium state
  GET  /api/triage       per-zone risk + projection, incident-aware (cheap, no LLM)
  POST /api/analyze      run the copilot over the current state (uses Gemini)
  POST /api/upload       replace the state with uploaded CSV real data
  POST /api/reset        restore the seeded demo state

The stadium state advances over time via a crowd-flow simulation, so the
dashboard reads like a live control room. Triage is cheap and refreshed on
every poll; the (costlier) LLM reasoning runs only on demand via /api/analyze.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .copilot import answer_question, build_report, zone_risks
from .data import parse_incidents_csv, parse_zones_csv, seed_snapshot
from .models import StadiumSnapshot
from .simulation import SimState, advance, etas_for, new_sim

logger = logging.getLogger(__name__)

app = FastAPI(title="MatchDay Ops Copilot", version="0.3.0")

_STATIC = Path(__file__).parent / "static"

MAX_UPLOAD_BYTES = 2_000_000  # reject oversized uploads before parsing
MAX_QUESTION_CHARS = 500      # cap free-text input to the copilot

# Self-contained CSP: no external origins (all CSS/JS is inline and same-origin).
_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")

# Single-process in-memory simulation is enough for a demo control room.
_state: dict[str, SimState] = {"sim": new_sim(seed_snapshot(), time.monotonic())}


class RateLimiter:
    """Fixed-window per-key limiter. Small, dependency-free, unit-testable."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, now: float) -> bool:
        bucket = self._hits.get(key)
        if bucket is None or now - bucket[0] >= self.window:
            self._hits[key] = [now, 1]
            return True
        if bucket[1] >= self.limit:
            return False
        bucket[1] += 1
        return True


# Generous: live polling is ~20/min; this only stops abuse.
_limiter = RateLimiter(limit=300, window=60.0)


def _advance_now() -> tuple[SimState, dict]:
    """Step the sim to the present and return it with fresh per-zone ETAs."""
    sim = _state["sim"]
    advance(sim, time.monotonic())
    return sim, etas_for(sim)


def _dataset_summary(snapshot: StadiumSnapshot) -> dict:
    """Aggregate stats for the upload confirmation: total capacity/occupancy,
    overall fill, and an incident-type breakdown."""
    total_capacity = sum(z.capacity for z in snapshot.zones)
    total_occupancy = sum(z.occupancy for z in snapshot.zones)
    incident_types: dict[str, int] = {}
    for incident in snapshot.incidents:
        incident_types[incident.type.value] = incident_types.get(incident.type.value, 0) + 1
    return {
        "total_capacity": total_capacity,
        "total_occupancy": total_occupancy,
        "overall_density": round(total_occupancy / total_capacity, 3) if total_capacity else 0.0,
        "incident_types": incident_types,
    }


@app.middleware("http")
async def security_and_limits(request: Request, call_next):
    """Rate-limit the API per client, then add baseline hardening headers."""
    if request.url.path.startswith("/api/"):
        client = request.client.host if request.client else "unknown"
        if not _limiter.allow(client, time.monotonic()):
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = _CSP
    return resp


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "genai_enabled": settings.genai_enabled,
            "model": settings.gemini_model if settings.genai_enabled else None}


@app.get("/api/snapshot")
def get_snapshot() -> dict:
    sim, _ = _advance_now()
    return sim.snapshot.model_dump()


@app.get("/api/triage")
def get_triage() -> dict:
    """Per-zone risk + forward projection. Cheap (no LLM) — safe to poll live."""
    sim, etas = _advance_now()
    snap = sim.snapshot
    zones = []
    for z, r in zone_risks(snap, etas=etas):
        eta = etas.get(z.id)
        zones.append({
            "zone_id": z.id, "name": z.name, "occupancy": z.occupancy,
            "capacity": z.capacity, "density": round(z.density, 3), "risk": r.value,
            "eta_seconds": round(eta) if eta is not None else None,
        })
    names = {z.id: z.name for z in snap.zones}
    incidents = [{
        "id": i.id, "type": i.type.value, "zone": names.get(i.zone_id, i.zone_id),
        "severity": i.severity, "description": i.description,
    } for i in snap.incidents if not i.resolved]
    return {"threshold": settings.crowd_alert_threshold,
            "zones": zones, "incidents": incidents}


@app.post("/api/analyze")
def analyze() -> JSONResponse:
    sim, etas = _advance_now()
    report = build_report(sim.snapshot, etas=etas)
    return JSONResponse(report.model_dump())


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)


@app.post("/api/ask")
def ask(req: AskRequest) -> JSONResponse:
    """Conversational copilot: answer an operator's question over the live state."""
    if not settings.genai_enabled:
        return JSONResponse(
            {"answer": "The copilot needs a configured Gemini key to answer.",
             "generated_by": "unavailable"})
    sim, etas = _advance_now()
    try:
        answer = answer_question(req.question, sim.snapshot, etas)
        return JSONResponse({"answer": answer, "generated_by": "gemini"})
    except Exception:
        logger.warning("Copilot ask failed", exc_info=True)
        return JSONResponse(
            {"answer": "The copilot is briefly unavailable — please retry.",
             "generated_by": "unavailable"}, status_code=503)


@app.post("/api/upload")
async def upload(zones: UploadFile = File(...),
                 incidents: UploadFile | None = File(None)) -> JSONResponse:
    raw = await zones.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "zones file too large"}, status_code=413)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JSONResponse({"error": "zones file must be UTF-8 CSV"}, status_code=400)

    result = parse_zones_csv(text)
    if result.zones_loaded == 0:
        return JSONResponse(
            {"error": "no valid zones parsed", "details": result.errors},
            status_code=400,
        )

    if incidents is not None:
        inc_raw = await incidents.read()
        if len(inc_raw) <= MAX_UPLOAD_BYTES:
            try:
                result.snapshot.incidents = parse_incidents_csv(inc_raw.decode("utf-8-sig"))
            except UnicodeDecodeError:
                pass  # incidents are optional; a bad file just means none loaded

    _state["sim"] = new_sim(result.snapshot, time.monotonic())
    return JSONResponse({
        "zones_loaded": result.zones_loaded,
        "incidents_loaded": len(result.snapshot.incidents),
        "errors": result.errors,
        **_dataset_summary(result.snapshot),
    })


@app.post("/api/reset")
def reset() -> dict:
    _state["sim"] = new_sim(seed_snapshot(), time.monotonic())
    return {"status": "reset"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


# Serve remaining static assets (kept after routes so "/" resolves to the page).
app.mount("/static", StaticFiles(directory=_STATIC), name="static")
