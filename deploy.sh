#!/usr/bin/env bash
set -euo pipefail

# Colors
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}==>${NC} $1"; }
warn() { echo -e "${YELLOW}WARN:${NC} $1"; }
err()  { echo -e "${RED}ERROR:${NC} $1"; exit 1; }

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
[ -f .env ] || err ".env not found. Copy .env.example to .env and fill in your values."
set -a; source .env; set +a

for var in GCP_PROJECT_ID GCP_REGION GEMINI_API_KEY GMAIL_USER GMAIL_APP_PASSWORD RECIPIENT_EMAIL; do
  [ -n "${!var:-}" ] || err "Missing required .env variable: $var"
done

FUNCTION_NAME="${FUNCTION_NAME:-arxiv-summarizer}"
SCHEDULER_JOB="arxiv-daily-digest"
SCHEDULER_SA="arxiv-scheduler-sa"

# ---------------------------------------------------------------------------
# 1. Create project
# ---------------------------------------------------------------------------
log "Creating GCP project: $GCP_PROJECT_ID"
gcloud projects create "$GCP_PROJECT_ID" --name="arXiv AI Summarizer" 2>/dev/null \
  || warn "Project may already exist — continuing."
gcloud config set project "$GCP_PROJECT_ID"

# ---------------------------------------------------------------------------
# 2. Billing (manual — required before APIs can be enabled)
# ---------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}ACTION REQUIRED:${NC} Enable billing for this project."
echo "  → https://console.cloud.google.com/billing/linkedaccount?project=${GCP_PROJECT_ID}"
echo ""
echo "Press Enter once billing is linked..."
read -r

# ---------------------------------------------------------------------------
# 3. Enable APIs
# ---------------------------------------------------------------------------
log "Enabling required APIs (this may take a minute)..."
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com

# ---------------------------------------------------------------------------
# 4. Deploy Cloud Function (gen2)
# ---------------------------------------------------------------------------
log "Deploying Cloud Function..."
gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --runtime=python312 \
  --region="$GCP_REGION" \
  --source=. \
  --entry-point=summarize_arxiv \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=512MB \
  --timeout=300s \
  --set-env-vars="GEMINI_API_KEY=${GEMINI_API_KEY},GMAIL_USER=${GMAIL_USER},GMAIL_APP_PASSWORD=${GMAIL_APP_PASSWORD},RECIPIENT_EMAIL=${RECIPIENT_EMAIL}"

FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
  --gen2 --region="$GCP_REGION" --format="value(serviceConfig.uri)")
log "Function URL: $FUNCTION_URL"

# ---------------------------------------------------------------------------
# 5. Service account for Cloud Scheduler
# ---------------------------------------------------------------------------
log "Creating scheduler service account..."
gcloud iam service-accounts create "$SCHEDULER_SA" \
  --display-name="arXiv Scheduler" 2>/dev/null \
  || warn "Service account already exists."

SA_EMAIL="${SCHEDULER_SA}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

log "Granting Cloud Run Invoker role to scheduler SA..."
gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
  --region="$GCP_REGION" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"

# ---------------------------------------------------------------------------
# 6. Cloud Scheduler — 4:00 PM Mountain Time, weekdays only
#    arXiv does not post on weekends, so we skip Sat/Sun.
# ---------------------------------------------------------------------------
log "Creating Cloud Scheduler job (Mon-Fri 4:00 PM Mountain Time)..."

SCHEDULER_ARGS=(
  --location="$GCP_REGION"
  --schedule="0 16 * * 1-5"
  --time-zone="America/Denver"
  --uri="$FUNCTION_URL"
  --http-method=GET
  --oidc-service-account-email="$SA_EMAIL"
  --oidc-token-audience="$FUNCTION_URL"
)

gcloud scheduler jobs create http "$SCHEDULER_JOB" "${SCHEDULER_ARGS[@]}" 2>/dev/null \
  || gcloud scheduler jobs update http "$SCHEDULER_JOB" "${SCHEDULER_ARGS[@]}"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
log "Deployment complete!"
echo ""
echo "Useful commands:"
echo "  Test now:    gcloud scheduler jobs run $SCHEDULER_JOB --location=$GCP_REGION"
echo "  View logs:   gcloud functions logs read $FUNCTION_NAME --gen2 --region=$GCP_REGION --limit=50"
echo "  List jobs:   gcloud scheduler jobs list --location=$GCP_REGION"
