# LinkedIn post — drafts

> ⚠️ POST THIS NEAR THE DEADLINE, not now — an early public post leaks the
>    approach to other participants (9-day window) for zero scoring benefit.
> ⚠️ The GitHub repo is PRIVATE. Only include the code link if you make it
>    public at submission time (and only if the contest needs judges to see code).
> 📸 Attach a screenshot / short screen-recording of the live app — the stadium
>    map + the recommendation with Spanish/French announcements is the money shot.
> ⏰ Best engagement window (India dev audience): ~9–11am or 7–9pm IST.
> 🏷️ Tag Google for Developers / Hack2Skill if the rules allow.

---

## ⭐ FINAL — polished, ready to post (recommended)

Most "stadium app" hackathon entries end up being a map with a chatbot bolted on. I wanted mine to make a **decision** instead.

For PromptWars Virtual Challenge 4, I built **MatchDay Ops Copilot** — real-time, explainable decision support for a FIFA World Cup 2026 stadium control room. I picked one persona (venue ops staff) and went deep on crowd management + operational intelligence, instead of trying to solve all four personas at once.

The scenario it handles: a gate hits 98% capacity *and* has an active medical incident. It doesn't just flash a number. Gemini reasons over the situation and tells staff exactly what to do — hold intake, open a responder lane, redirect to Gate D — *and why* — plus a calm public-address message in English, Spanish and French.

As a backend developer, the split that mattered to me:
→ **I designed** the deterministic parts — triage rules, relief-zone routing, data ingestion, tests. Cheap, fast, fully testable.
→ **Gemini did what rules can't** — fusing "98% + medical incident" into a safety judgment, and writing tone-aware announcements in three languages. Delete the model and you lose the reasoning and the comms, not just a nice-to-have.

But the part I'm actually proud of isn't the prompt — it's the reliability. In testing, Gemini's free tier threw me a retired-model 404 and overload 429/503s that silently dropped the app to a non-AI fallback. Unacceptable when the AI is the point. So I added: a `-latest` model alias so a pinned model can't retire mid-contest, retries with jittered backoff, and automatic failover to a lighter model. It now serves real multilingual reasoning even under load.

Tools: **Gemini** (`flash` — cost-optimized on purpose; the challenge rewards engineering, not the biggest model), **FastAPI**, **Docker**, **pytest** (46 tests, edge-case heavy). I also used structured-output mode + few-shot examples to lock the tone.

"Vibe coding" got me moving fast. Thinking like an engineer — tests, cost, graceful degradation — is what made it production-ready.

🔗 Live demo: https://matchday-ops-copilot.onrender.com

— Suma

#PromptWars #BuildWithAI #GoogleAI #Gemini #GenAI #FIFAWorldCup2026 #BackendEngineering #SoftwareEngineering

---

### Alternate drafts below (if you want shorter or more detailed)

---

## OPTION A — short & punchy (higher engagement)

Most stadium apps for a hackathon are a map + a chatbot. I wanted mine to make a **decision**.

For PromptWars Challenge 4 I built **MatchDay Ops Copilot** — real-time decision support for a FIFA World Cup 2026 control room.

When a gate hits 98% AND has a medical incident, it doesn't just show a number. Gemini reasons over it and tells the staff: *hold intake, redirect to Gate D, here's why* — plus a calm public-address message in English, Spanish & French.

The split that mattered to me as a backend dev:
→ I wrote the rules (triage, routing, tests).
→ Gemini did what rules can't: the reasoning + the multilingual, tone-aware comms.

Hardest part wasn't the prompt — it was reliability. Gemini's free tier threw retired-model 404s and overload 429/503s that silently killed the AI. So I added model failover + retry with backoff. It now stays live under load.

🔗 Live: https://matchday-ops-copilot.onrender.com
💻 Code: https://github.com/sumajavadev25/matchday-ops-copilot

Built with Gemini + FastAPI. "Vibe coding" got me fast; thinking like an engineer got it production-ready.

#PromptWars #BuildWithAI #Gemini #GenAI #SoftwareEngineering

---

## OPTION B — detailed (documents everything the rubric asks)


🏟️ I built **MatchDay Ops Copilot** for PromptWars Virtual Challenge 4 — an explainable, real-time decision-support tool for a FIFA World Cup 2026 stadium control room.

🔗 Live: https://matchday-ops-copilot.onrender.com
💻 Code: https://github.com/sumajavadev25/matchday-ops-copilot

**The problem I picked (one persona, two verticals)**
The brief lists 4 personas and 8 verticals — the trap is trying to do all of them. I went narrow: **organizers / venue staff**, focused on **crowd management + operational intelligence**. One question: when a gate is about to bottleneck, what's the *one* decision that makes the next 5 minutes safer?

**How it works**
It ingests live zone occupancy + incidents, then:
1. A deterministic triage layer scores every zone (crowd density + incident severity) → normal / elevated / high / critical.
2. Gemini turns each flagged zone into an *explainable* recommendation — the reasoning, the action, and a ready-to-broadcast announcement in English, Spanish & French.

**What GenAI handled vs. what I designed**
This distinction mattered to me as a backend engineer. I *designed* the triage rules, relief-zone routing, the data-ingestion contract, and the tests — that's cheap, fast, fully testable logic. **Gemini did the part rules can't fake:** fusing "98% density + a medical incident" into a safety judgment, and writing calm, register-appropriate multilingual announcements. If you deleted the model, you'd lose the reasoning and the comms — not just a nice-to-have.

**Tools & why**
- **Google Gemini (`gemini-flash-latest`)** — the reasoning + generation core. Chose flash (not the biggest model) because the challenge rewards engineering over "fanciest model," and flash is cost-optimized.
- **Claude** — my pair-programmer for architecture, backend, and tests.
- **FastAPI + Pydantic**, **Docker**, **Render** for deploy, **pytest** (44 tests, edge-case heavy).

**How my prompts evolved**
- v1: a single structured prompt returning JSON (reasoning + action + announcements).
- v2: added **context-aware register** — medical/security incidents get a calm, reassuring tone (no alarming words); a restroom queue gets a light, matter-of-fact one. Same copilot, situational voice.

**The real engineering story: reliability**
The hard part wasn't the prompt — it was making a *mandatory* external dependency trustworthy. In testing I hit a retired model (404) and overload/rate-limits (503/429) that silently dropped the app to a non-AI fallback. Fixes: use the `-latest` model alias so a pinned model can't retire mid-contest, retry transient overloads with jittered backoff, and **fail over to a lighter model** before ever degrading. Result: real Gemini multilingual output even under load.

Takeaway: "vibe coding" got me moving fast, but thinking like an engineer — tests, cost, graceful degradation — is what makes an AI feature production-ready.

#PromptWars #BuildWithAI #GoogleAI #Gemini #GenAI #FIFAWorldCup2026 #SoftwareEngineering
