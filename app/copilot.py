"""The decision-support core.

Two layers, deliberately separated:

1. Deterministic triage (`assess_zone`) — cheap, O(zones + incidents), fully
   unit-testable. Decides *which* zones need attention and how urgently.
2. Generative reasoning (`generate_reasoning`) — Gemini turns the triage into a
   plain-language explanation and ready-to-broadcast multilingual announcements.
   This is the part that genuinely needs generation, not rules.

If no API key is configured the report still builds via a transparent fallback
(marked `generated_by="fallback"`) so the app never hard-fails in dev or tests.
GenAI is the intended production path and is required at evaluation time.
"""
from __future__ import annotations

import json
import logging
import random
import time

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from .config import settings

logger = logging.getLogger(__name__)
from .models import (
    CopilotReport,
    Incident,
    Recommendation,
    RiskLevel,
    StadiumSnapshot,
    Zone,
)

# Languages the announcements are generated in. FIFA WC 2026 is USA/Canada/Mexico.
_DEFAULT_LANGS = ["en", "es", "fr"]

# Retry policy for transient Gemini overload (503). Backoff in seconds, with
# jitter so concurrent requests don't retry in lockstep under load.
_MAX_RETRIES = 4
_RETRY_BACKOFF = 1.5


# --- Structured output schema -------------------------------------------------
# Passed to Gemini as `response_schema` so the model returns schema-valid JSON.
# announcements is a list (not a dict) because structured output needs fixed
# fields, not arbitrary language keys; we fold it back to {lang: text} on the way
# out. This lets us drop the fragile fence-stripping text parser as the primary.
class _GenAnnouncement(BaseModel):
    lang: str
    text: str


class _GenRecommendation(BaseModel):
    zone_id: str
    headline: str
    reasoning: str
    action: str
    announcements: list[_GenAnnouncement]


def assess_zone(zone: Zone, incidents: list[Incident], threshold: float) -> RiskLevel:
    """Rule-based triage for a single zone. Deterministic and side-effect free."""
    density = zone.density
    max_sev = max((i.severity for i in incidents
                   if i.zone_id == zone.id and not i.resolved), default=0)

    # A high-severity incident escalates regardless of crowd level.
    if max_sev >= 4 or density >= 1.0:
        return RiskLevel.CRITICAL
    if density >= threshold or max_sev == 3:
        return RiskLevel.HIGH
    if density >= threshold * 0.85 or max_sev in (1, 2):
        return RiskLevel.ELEVATED
    return RiskLevel.NORMAL


_RISK_ORDER = {RiskLevel.NORMAL: 0, RiskLevel.ELEVATED: 1,
               RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


def _eta_risk(eta_seconds: float | None) -> RiskLevel:
    """Turn a projected time-to-capacity into a risk level. This is what makes
    the copilot predictive: a zone filling fast is urgent *before* it's full."""
    if eta_seconds is None:
        return RiskLevel.NORMAL
    if eta_seconds <= 60:
        return RiskLevel.CRITICAL
    if eta_seconds <= 150:
        return RiskLevel.HIGH
    if eta_seconds <= 300:
        return RiskLevel.ELEVATED
    return RiskLevel.NORMAL


def _density_ceiling(density: float) -> RiskLevel:
    """The most severe level the *projection* alone may raise a zone to, given
    how full it actually is. A half-empty gate that's merely trending up is not
    a crush — you still have buffer — so prediction can nudge but not scream."""
    if density >= 0.75:
        return RiskLevel.CRITICAL
    if density >= 0.55:
        return RiskLevel.HIGH
    if density >= 0.35:
        return RiskLevel.ELEVATED
    return RiskLevel.NORMAL


def combined_risk(zone: Zone, incidents: list[Incident], threshold: float,
                  eta_seconds: float | None = None) -> RiskLevel:
    """The worse of current-state triage and the (density-capped) projection."""
    base = assess_zone(zone, incidents, threshold)
    ceiling = _density_ceiling(zone.density)
    pred = min(_eta_risk(eta_seconds), ceiling, key=lambda r: _RISK_ORDER[r])
    return max(base, pred, key=lambda r: _RISK_ORDER[r])


def _relief_order(snapshot: StadiumSnapshot) -> list[Zone]:
    """All zones sorted least-to-most crowded. Computed once per report so
    picking a relief zone for every flagged zone is O(1) lookup instead of an
    O(zones) rescan each time — O(n log n) total instead of O(k·n)."""
    return sorted(snapshot.zones, key=lambda z: z.density)


def _suggest_relief_zone(zone: Zone, relief_order: list[Zone]) -> Zone | None:
    """Least-crowded zone other than `zone` itself, from a precomputed order."""
    for candidate in relief_order:
        if candidate.id != zone.id:
            return candidate
    return None


def zone_risks(snapshot: StadiumSnapshot,
               threshold: float | None = None,
               etas: dict[str, float | None] | None = None,
               ) -> list[tuple[Zone, RiskLevel]]:
    """Risk for every zone (including normal ones). Single source of truth for
    the dashboard table so it can't drift from the copilot's triage.
    When `etas` is supplied, risk also accounts for the forward projection."""
    threshold = settings.crowd_alert_threshold if threshold is None else threshold
    etas = etas or {}
    return [(z, combined_risk(z, snapshot.incidents, threshold, etas.get(z.id)))
            for z in snapshot.zones]


def triage(snapshot: StadiumSnapshot, threshold: float,
           etas: dict[str, float | None] | None = None,
           ) -> list[tuple[Zone, RiskLevel]]:
    """All zones needing attention (ELEVATED+), most severe first.

    Built on `zone_risks()` rather than recomputing `combined_risk` per zone,
    so the two never drift and the work isn't done twice.
    """
    scored = zone_risks(snapshot, threshold, etas)
    flagged = [(z, r) for z, r in scored if r != RiskLevel.NORMAL]
    # _RISK_ORDER ascends NORMAL→CRITICAL; negate it to sort most-severe first.
    flagged.sort(key=lambda pair: (-_RISK_ORDER[pair[1]], -pair[0].density))
    return flagged


def _fallback_recommendation(zone: Zone, risk: RiskLevel, relief: Zone | None) -> Recommendation:
    pct = round(zone.density * 100)
    where = f" Redirect arriving fans to {relief.name}." if relief else ""
    action = f"Hold intake at {zone.name}.{where}"
    msg = f"{zone.name} is busy. Please follow steward directions" + (
        f" toward {relief.name}." if relief else "."
    )
    return Recommendation(
        zone_id=zone.id,
        zone_name=zone.name,
        risk=risk,
        density=round(zone.density, 3),
        headline=f"{zone.name} at {pct}% capacity",
        reasoning=(
            f"{zone.name} is at {pct}% of its {zone.capacity:,} capacity, "
            f"triaged as {risk.value}. Acting now prevents a bottleneck."
        ),
        action=action,
        announcements={"en": msg},
    )


def _open_incidents_by_zone(snapshot: StadiumSnapshot) -> dict[str, list[Incident]]:
    """Group unresolved incidents by zone id in a single pass, so callers don't
    rescan the incident list once per zone."""
    grouped: dict[str, list[Incident]] = {}
    for incident in snapshot.incidents:
        if not incident.resolved:
            grouped.setdefault(incident.zone_id, []).append(incident)
    return grouped


def _assemble_recommendation(zone: Zone, risk: RiskLevel, relief: Zone | None,
                             gen: dict | None) -> Recommendation:
    """Build a Recommendation from Gemini output when present, else the
    deterministic fallback. Keeps `build_report` focused on orchestration."""
    if not gen:
        return _fallback_recommendation(zone, risk, relief)
    return Recommendation(
        zone_id=zone.id,
        zone_name=zone.name,
        risk=risk,
        density=round(zone.density, 3),
        headline=gen.get("headline", f"{zone.name} needs attention"),
        reasoning=gen.get("reasoning", ""),
        action=gen.get("action", ""),
        announcements={k: v for k, v in gen.get("announcements", {}).items() if v},
    )


def _build_prompt(items: list[tuple[Zone, RiskLevel, Zone | None]],
                  snapshot: StadiumSnapshot, langs: list[str],
                  etas: dict[str, float | None] | None = None) -> str:
    etas = etas or {}
    open_by_zone = _open_incidents_by_zone(snapshot)
    payload = []
    for zone, risk, relief in items:
        open_inc = [i.model_dump() for i in open_by_zone.get(zone.id, ())]
        eta = etas.get(zone.id)
        payload.append({
            "zone_id": zone.id,
            "zone_name": zone.name,
            "risk": risk.value,
            "density_pct": round(zone.density * 100),
            "capacity": zone.capacity,
            "occupancy": zone.occupancy,
            "projected_full_in_seconds": round(eta) if eta is not None else None,
            "open_incidents": open_inc,
            "suggested_relief_zone": relief.name if relief else None,
        })
    return (
        "You are the operations copilot in a FIFA World Cup 2026 stadium control room. "
        "For each flagged zone below, produce an explainable recommendation for venue "
        "staff. Be specific and operational; every recommendation MUST justify itself.\n\n"
        "GROUND every statement in the data provided — cite the density, the "
        "projected_full_in_seconds, and any open_incidents. Do NOT invent specific "
        "turnstile numbers, staff names, facilities, or details that are not in the "
        "data. If a zone is projected to fill soon, say so and treat it as urgent.\n\n"
        f"Flagged zones (JSON):\n{json.dumps(payload, indent=2)}\n\n"
        "Announcement register — match tone to the situation, do not use one flat "
        "voice:\n"
        "  - medical or security incident: calm, authoritative, reassuring; lead with "
        "safety, avoid alarming words like 'emergency' or 'danger'.\n"
        "  - crowd/capacity only: brisk and directive, emphasise the faster alternative.\n"
        "  - facility/comfort issue: light, matter-of-fact, not urgent.\n"
        "Keep each announcement to one or two sentences a nervous, non-local fan can "
        "act on immediately.\n\n"
        + _FEW_SHOT
        + f"\nProduce one recommendation per flagged zone. Every 'reasoning' must say "
        "WHY it is a risk and why the action helps. Include an announcement for each "
        f"of these languages: {langs}."
    )


# One worked example per register (medical vs. facility) to lock tone. Kept
# compact; the response schema handles structure so we only teach *voice* here.
_FEW_SHOT = (
    "Examples of the expected voice:\n"
    "1) Zone at 97% with a severity-4 medical incident, relief zone 'Gate 8' →\n"
    '   reasoning: "At 97% with an active medical incident, the crowd is blocking '
    'responders; holding intake and diverting to Gate 8 clears access and prevents a '
    'crush." action: "Hold Gate 7 intake, open a responder lane, redirect arrivals to '
    'Gate 8 with stewards." announcement (en): "For your safety, please continue to '
    'Gate 8 for entry while our team assists a supporter." (calm, safety-first, never '
    'says \'emergency\').\n'
    "2) Zone at 70% with a restroom-overflow facility incident →\n"
    '   announcement (en): "The restrooms here are busy right now — additional '
    'facilities are a short walk toward Gate D." (light, matter-of-fact, not urgent).\n\n'
)


def _parse_model_json(raw: str) -> list[dict]:
    """Tolerate ```json fences and leading/trailing prose around the array.

    Only a safety net now that structured output is requested — but kept so a
    model or SDK that ignores the schema still parses.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in model output")
    return json.loads(text[start:end + 1])


def _rows_from_response(resp: object) -> dict[str, dict]:
    """Normalise a model response into {zone_id: fields}, folding the
    announcements list back into a {lang: text} dict. Prefers the SDK's parsed
    structured output; falls back to lenient text parsing."""
    parsed = getattr(resp, "parsed", None)
    if parsed:
        rows = [p.model_dump() if hasattr(p, "model_dump") else dict(p) for p in parsed]
    else:
        rows = _parse_model_json(resp.text)

    out: dict[str, dict] = {}
    for row in rows:
        zid = row.get("zone_id")
        if not zid:
            continue
        ann = row.get("announcements", {})
        if isinstance(ann, list):
            ann = {a.get("lang"): a.get("text") for a in ann
                   if a.get("lang") and a.get("text")}
        row["announcements"] = ann
        out[zid] = row
    return out


def _generate_with_failover(contents: str, config: "types.GenerateContentConfig | None"):
    """Run a Gemini call across the model chain with our resilience policy.

    For each model (primary, then a lighter fallback): retry transient 5xx
    overloads with jittered backoff; on 429 rate-limit or a retired/invalid
    model, move straight to the next model. Shared by every LLM feature so the
    reliability engineering lives in exactly one place.
    """
    client = genai.Client(api_key=settings.gemini_api_key)
    models = [settings.gemini_model]
    if settings.gemini_fallback_model and settings.gemini_fallback_model not in models:
        models.append(settings.gemini_fallback_model)

    last_exc: Exception | None = None
    for model in models:
        for attempt in range(_MAX_RETRIES):
            try:
                return client.models.generate_content(
                    model=model, contents=contents, config=config)
            except errors.ServerError as exc:  # 5xx overload — retry this model
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BACKOFF * (2 ** attempt) * (0.5 + random.random()))
            except errors.ClientError as exc:  # 429/404 etc. — try the next model
                last_exc = exc
                break
    raise last_exc if last_exc else RuntimeError("gemini call failed")


def generate_reasoning(items: list[tuple[Zone, RiskLevel, Zone | None]],
                       snapshot: StadiumSnapshot,
                       langs: list[str],
                       etas: dict[str, float | None] | None = None) -> dict[str, dict]:
    """Call Gemini for explanations + announcements. Returns {zone_id: fields}."""
    prompt = _build_prompt(items, snapshot, langs, etas)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=list[_GenRecommendation],
        temperature=0.5,
    )
    resp = _generate_with_failover(prompt, config)
    return _rows_from_response(resp)


def _state_briefing(snapshot: StadiumSnapshot,
                    etas: dict[str, float | None] | None = None) -> str:
    """Compact JSON of the live state the copilot may reason over."""
    etas = etas or {}
    zones = []
    for z in snapshot.zones:
        eta = etas.get(z.id)
        zones.append({
            "zone": z.name, "density_pct": round(z.density * 100),
            "occupancy": z.occupancy, "capacity": z.capacity,
            "projected_full_in_seconds": round(eta) if eta is not None else None,
            "risk": combined_risk(z, snapshot.incidents,
                                  settings.crowd_alert_threshold, eta).value,
        })
    incidents = [{"type": i.type.value, "zone_id": i.zone_id, "severity": i.severity,
                  "description": i.description}
                 for i in snapshot.incidents if not i.resolved]
    return json.dumps({"zones": zones, "incidents": incidents}, indent=2)


def answer_question(question: str, snapshot: StadiumSnapshot,
                    etas: dict[str, float | None] | None = None) -> str:
    """Answer an operator's free-text question, grounded in the live state.

    Turns the tool from a one-shot report generator into a conversational
    copilot: supports "what's my top priority?" and "what if I close Gate B?".
    """
    briefing = _state_briefing(snapshot, etas)
    prompt = (
        "You are the operations copilot in a FIFA World Cup 2026 stadium control "
        "room. Answer the control-room operator's question using ONLY the live "
        "state below. Be concise and operational (2-4 sentences). Cite specific "
        "zones, densities, and projections. For 'what if' questions, reason from "
        "the data about the likely effect (e.g., closing a gate pushes its inflow "
        "to the relief zone). If the data cannot answer it, say so plainly. Do "
        "NOT invent zones, numbers, staff, or facilities not present in the data.\n\n"
        f"Live state (JSON):\n{briefing}\n\n"
        f"Operator question: {question.strip()}"
    )
    resp = _generate_with_failover(prompt, None)
    return (resp.text or "").strip()


def build_report(snapshot: StadiumSnapshot,
                 threshold: float | None = None,
                 langs: list[str] | None = None,
                 etas: dict[str, float | None] | None = None) -> CopilotReport:
    """Full pipeline: triage → (Gemini reasoning | fallback) → assembled report.
    `etas` (projected seconds-to-capacity per zone) makes triage and the model
    reasoning predictive, not just reactive."""
    threshold = settings.crowd_alert_threshold if threshold is None else threshold
    langs = langs or _DEFAULT_LANGS

    flagged = triage(snapshot, threshold, etas)
    relief_order = _relief_order(snapshot)
    items = [(z, r, _suggest_relief_zone(z, relief_order)) for z, r in flagged]

    if not items:
        return CopilotReport(generated_by="none", threshold=threshold,
                             summary="All zones nominal. No action required.")

    generated_by = "fallback"
    reasoning_by_zone: dict[str, dict] = {}
    if settings.genai_enabled:
        try:
            reasoning_by_zone = generate_reasoning(items, snapshot, langs, etas)
            generated_by = "gemini"
        except Exception:
            # Never let a model hiccup take down the control room — degrade to the
            # deterministic fallback, but record why so failures aren't silent.
            logger.warning("Gemini reasoning failed; using fallback", exc_info=True)
            generated_by = "fallback"

    recs = [_assemble_recommendation(zone, risk, relief, reasoning_by_zone.get(zone.id))
            for zone, risk, relief in items]

    critical = sum(1 for _, r, _ in items if r == RiskLevel.CRITICAL)
    summary = (f"{len(items)} zone(s) flagged, {critical} critical. "
               "Prioritise critical zones first.")
    return CopilotReport(generated_by=generated_by, threshold=threshold,
                         recommendations=recs, summary=summary)
