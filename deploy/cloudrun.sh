#!/usr/bin/env bash
# One-command Cloud Run deploy. Run from the repo root: ./deploy/cloudrun.sh
# Prereqs: gcloud installed + `gcloud init` done + billing enabled on the project.
set -euo pipefail

REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-matchday-ops}"

# Pull the key from .env so it's never hard-coded here.
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi
: "${GEMINI_API_KEY:?Set GEMINI_API_KEY in .env before deploying}"
MODEL="${GEMINI_MODEL:-gemini-flash-latest}"

echo "Deploying $SERVICE to Cloud Run ($REGION)…"
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars "GEMINI_API_KEY=${GEMINI_API_KEY},GEMINI_MODEL=${MODEL}"

echo "Done. URL above ^. Test it: curl \$URL/api/health"
