# Demo script & submission checklist

A 60–90s guided walkthrough — record this as a short screen video for the
LinkedIn post, and follow it yourself right before submitting so the app is warm
for evaluators.

## ⚠️ Warm it first (Render free tier sleeps ~15 min idle)
Right before submitting, open the app and click **Run analysis** once. The first
hit after idle takes ~50s; after that it's instant. Do this so a judge never
lands on a cold instance.

## Walkthrough (what to show, in order)

1. **The control room (5s).** Open the app. Point out the **stadium map** —
   zones around the pitch, coloured by risk, Gate C pulsing red (critical).

2. **Go live (15s).** Click **▶ Go live**. Watch the crowd numbers climb, the map
   recolour, and the **"Fills in"** column tick down. Say: *"the state advances in
   real time; triage refreshes every 3s without touching the LLM — cost-aware."*

3. **Predictive, not reactive (10s).** Point at a mid-density zone flagged early
   (e.g. North Concourse ~65% but HIGH because it fills in a few minutes). Say:
   *"density alone would miss this — the projection flags it before it's full."*

4. **Explainable GenAI (15s).** Click **Run analysis**. Show a recommendation:
   the **why**, the **action**, and the **English / Spanish / French** announcement.
   Note Gate C's calm, safety-first tone vs. a casual facility message.

5. **Ask the copilot (20s).** Type or click **"What if I close Gate B?"**. Show the
   grounded answer reasoning about diverting flow and *avoiding* the already-critical
   Gate C. Say: *"it's a conversational copilot, not just a report."*

6. **Real data (15s).** In **Upload real data**, upload `sample_data/zones.csv` +
   `incidents.csv`. Show it re-analyses your data live. Say: *"evaluators can drop
   in their own CSV — nothing is hardcoded."*

## Submission checklist
- [ ] Rotate the Gemini API key; update it in Render → redeploy
- [ ] Warm the app (open + Run analysis)
- [ ] Post the LinkedIn writeup (see `LINKEDIN_POST.md`); attach the demo video
- [ ] Submit the deployment URL + LinkedIn post URL on the platform
- [ ] Remember: only 3 attempts, and the LATEST is scored — submit your best state
