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

import time
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .copilot import build_report, zone_risks
from .data import parse_incidents_csv, parse_zones_csv, seed_snapshot
from .simulation import SimState, advance, etas_for, new_sim

app = FastAPI(title="MatchDay Ops Copilot", version="0.2.0")

_STATIC = Path(__file__).parent / "static"

MAX_UPLOAD_BYTES = 2_000_000  # reject oversized uploads before parsing

# Single-process in-memory simulation is enough for a demo control room.
_state: dict[str, SimState] = {"sim": new_sim(seed_snapshot(), time.monotonic())}


def _advance_now() -> tuple[SimState, dict]:
    """Step the sim to the present and return it with fresh per-zone ETAs."""
    sim = _state["sim"]
    advance(sim, time.monotonic())
    return sim, etas_for(sim)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening headers on every response."""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
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
