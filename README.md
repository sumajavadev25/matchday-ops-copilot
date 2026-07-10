# MatchDay Ops Copilot

Explainable, real-time decision support for a FIFA World Cup 2026 stadium
control room. Built for **PromptWars: Virtual — Challenge 4 (Smart Stadiums &
Tournament Operations).**

**Persona:** organizers / venue staff.
**Verticals:** crowd management + operational intelligence (with multilingual
public-address as the action layer).

## What it does

Ingests live zone occupancy and incident data, then the copilot:

1. **Triages** every zone deterministically (crowd density + incident severity)
   into normal / elevated / high / critical.
2. **Explains** each flagged zone with Gemini — *why* it's a risk, *what* to do,
   and a ready-to-broadcast announcement in multiple languages.

The GenAI does the part that genuinely needs generation — reasoning and
context-appropriate multilingual comms — while the cheap, testable rule layer
handles triage. (Answering the judges' "could this just be rule-based?" test.)

## Why GenAI is required, not decorative

Triage is rules. But turning "gate-c: 98%, sev-4 medical" into a calm,
register-appropriate crowd announcement in English/Spanish/French — and a
staff-facing justification — is generation that rules can't fake.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your GEMINI_API_KEY (from aistudio.google.com/apikey)
uvicorn app.main:app --reload
# open http://localhost:8000
```

Without a key the app still runs in a transparent **fallback** mode (marked in
the response) so it never hard-fails. GenAI is required at evaluation time.

## Test

```bash
pytest -q      # 35 tests, heavy on edge cases (zero-capacity, over-capacity,
               # malformed CSV rows, missing columns, incident escalation)
```

## Evaluators: upload your own real data

The dashboard's **Upload real data** panel accepts:

- **zones.csv** — `id,name,capacity,occupancy[,lat,lng]`
- **incidents.csv** (optional) — `id,type,zone_id,severity[,description,resolved]`

Sample files are in [`sample_data/`](sample_data/). Parsing is defensive:
unknown columns ignored, bad rows reported (not silently dropped), missing
required columns rejected with a clear message.

## Deploy (Cloud Run)

```bash
gcloud run deploy matchday-ops \
  --source . --region us-central1 --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=YOUR_KEY,GEMINI_MODEL=gemini-2.5-flash
```

## Architecture

```
CSV upload / seed ─▶ StadiumSnapshot ─▶ triage() ─▶ Gemini reasoning ─▶ Report ─▶ dashboard
                     (models.py)        (copilot.py, deterministic)   (copilot.py)
```

See [DECISIONS.md](DECISIONS.md) for the tool-usage and prompt-evolution log.
