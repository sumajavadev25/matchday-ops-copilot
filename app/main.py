"""FastAPI surface for the MatchDay Ops Copilot.

Endpoints:
  GET  /                 accessible control-room dashboard
  GET  /api/health       liveness + whether GenAI is configured
  GET  /api/snapshot     current stadium state (seed or last upload)
  POST /api/analyze      run the copilot over the current snapshot
  POST /api/upload       replace the snapshot with uploaded CSV real data
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .copilot import build_report, zone_risks
from .data import parse_incidents_csv, parse_zones_csv, seed_snapshot
from .models import StadiumSnapshot

app = FastAPI(title="MatchDay Ops Copilot", version="0.1.0")

_STATIC = Path(__file__).parent / "static"

# Single-process in-memory state is enough for a demo control room.
_state: dict[str, StadiumSnapshot] = {"snapshot": seed_snapshot()}

MAX_UPLOAD_BYTES = 2_000_000  # reject oversized uploads before parsing


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
def get_snapshot() -> StadiumSnapshot:
    return _state["snapshot"]


@app.get("/api/triage")
def get_triage() -> dict:
    """Per-zone risk (incident-aware) for the dashboard table."""
    snap = _state["snapshot"]
    zones = [{
        "zone_id": z.id, "name": z.name, "occupancy": z.occupancy,
        "capacity": z.capacity, "density": round(z.density, 3), "risk": r.value,
    } for z, r in zone_risks(snap)]
    names = {z.id: z.name for z in snap.zones}
    incidents = [{
        "id": i.id, "type": i.type.value, "zone": names.get(i.zone_id, i.zone_id),
        "severity": i.severity, "description": i.description,
    } for i in snap.incidents if not i.resolved]
    return {"threshold": settings.crowd_alert_threshold,
            "zones": zones, "incidents": incidents}


@app.post("/api/analyze")
def analyze() -> JSONResponse:
    report = build_report(_state["snapshot"])
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

    _state["snapshot"] = result.snapshot
    return JSONResponse({
        "zones_loaded": result.zones_loaded,
        "incidents_loaded": len(result.snapshot.incidents),
        "errors": result.errors,
    })


@app.post("/api/reset")
def reset() -> dict:
    _state["snapshot"] = seed_snapshot()
    return {"status": "reset"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


# Serve remaining static assets (kept after routes so "/" resolves to the page).
app.mount("/static", StaticFiles(directory=_STATIC), name="static")
