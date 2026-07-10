# Decisions & prompt-evolution log

Running log for the mandatory LinkedIn submission: which tools, why, how prompts
evolved, and what GenAI handled vs. what I designed. Append as you build.

## Tools used

| Tool | Role | Why |
|------|------|-----|
| Claude (Claude Code) | Architecture, backend code, tests, this repo | Allowed per rules; fastest for backend + test design |
| Google Gemini (`gemini-2.5-flash`) | Runtime reasoning + multilingual announcements | GenAI requirement; flash is cost-optimized (judges reward engineering, not "fanciest model") |
| FastAPI + Pydantic | API + typed domain models | Clean validation = fewer edge-case bugs = higher code-quality score |
| Cloud Run (deploy target) | Hosting | Counts toward the "Google Services" scoring signal |
| pytest | 35 tests, edge-case heavy | Testing is a scored signal; edge cases are where most entries drop points |

## What GenAI handled vs. what I designed

- **I designed:** the deterministic triage (density + incident severity →
  risk level), the relief-zone selection, the CSV ingestion contract, the API
  surface, and all tests. These are rules — cheap, fast, fully testable.
- **GenAI (Gemini) handled:** turning a triaged zone into a plain-language
  justification and calm, register-appropriate announcements in EN/ES/FR. This
  is generation that rules can't fake — the reason GenAI is load-bearing here.

## Design principle: GenAI must be load-bearing

The rubric asks "could this be plain rule-based code instead?" So the split is
deliberate: rules do triage, the model does the reasoning + generation that only
a model can. If you deleted Gemini, you'd lose the explanations and the
multilingual comms — not just a nice-to-have.

## Prompt evolution

- **v1:** single structured prompt — feeds flagged zones as JSON, asks for a
  JSON array of `{headline, reasoning, action, announcements{lang}}`. Output
  parsing tolerates ```json fences and surrounding prose.
- **v2 (current):** context-aware announcement **register** — the prompt now
  instructs different tones by incident type (medical/security = calm,
  reassuring, no alarming words; crowd = brisk, directive; facility = light,
  matter-of-fact). Verified live: a medical-zone message leads with safety and
  avoids "emergency," while a restroom-queue message is casual — same copilot,
  situationally-appropriate voice. This is the register distinction the SME
  explicitly praised in the explainer session.
- **v3 (current):** **structured output + few-shot.** The Gemini call now sends
  `response_schema` (a Pydantic model) with `response_mime_type=application/json`,
  so every response is schema-valid — the tolerant fence-stripping parser is now
  just a safety net, not the primary path. Added two compact few-shot examples
  (a medical case and a facility case) that lock the register; announcements are
  modelled as a `list[{lang,text}]` (structured output needs fixed fields, not
  arbitrary dict keys) and folded back to `{lang: text}`. Verified live: cleaner,
  more consistent tone and all requested languages present every call.

## Reliability engineering (real story for the post)

Live testing hit two real failure modes against the free tier, both fixed:

1. **Retired model.** The first pinned model (`gemini-2.5-flash`) returned 404
   "no longer available to new users." Fix: default to the `gemini-flash-latest`
   alias, which tracks the current flash and can't retire out from under us at
   evaluation time.
2. **Overload / rate-limit.** Under load the primary flash returned 503 (high
   demand) and 429 (quota). A single failure silently dropped the app to the
   non-AI fallback — unacceptable when GenAI must be functional at judging time.
   Fix: `generate_reasoning` now (a) retries 5xx with jittered exponential
   backoff, and (b) fails over to a lighter model (`gemini-flash-lite-latest`,
   higher free-tier limits + cheaper) before ever degrading. Verified: the app
   returns real Gemini multilingual output even mid-overload.

Takeaway for the post: the interesting engineering wasn't the prompt — it was
making a mandatory external dependency reliable enough to trust in production.

## Real-time + predictive (the "control room" upgrade)

Two additions that move it from a static demo to a live tool:

- **Live crowd-flow simulation** (`simulation.py`): the stadium state advances
  over time (persons/sec per zone, deterministic stepping, "redirect relief"
  when a gate fills). A **Go live** toggle polls the *cheap* `/api/triage`
  (no LLM) every 3s, so the board moves and the map recolours in real time —
  while the costlier Gemini reasoning stays on-demand (cost-aware by design).
- **Predictive time-to-capacity**: each zone projects seconds-to-full from its
  current inflow. Triage now takes the worse of current-state and projection,
  so a zone at 65% that's filling fast is flagged **HIGH before it's full** —
  genuine "operational intelligence", not just a live dashboard. The projection
  is fed to Gemini too, so reasoning reads "…full in ~52s, redirect now".

## Grounding

Prompt now instructs the model to cite only the provided data (density,
projected_full_in_seconds, open_incidents) and to NOT invent turnstile numbers,
staff, or facilities. Removes the plausible-but-ungrounded specifics a judge
would probe.

## Scoring levers deliberately targeted

- **Testing:** 35 tests, edge cases first (zero/over capacity, malformed CSV).
- **Code quality:** single-pass O(n) triage & relief selection; typed models.
- **Security:** upload size cap, UTF-8 validation, no secrets in code.
- **Accessibility:** semantic HTML, skip link, ARIA live regions, visible focus,
  contrast in light + dark.
- **Google Services:** Cloud Run deploy + Gemini (+ Maps API planned for zone map).
- **Problem alignment:** one persona, two verticals, explainable output — exactly
  the "input → reasoning → action" loop the SME described.
- **Real-data handling:** evaluator CSV upload path, per the Q&A.
