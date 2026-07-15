#!/usr/bin/env bash
#
# Build + deploy the MCP server to Cloud Run.
#
# Idempotent: each invocation runs `gcloud run deploy --source .`, which
# rebuilds the image via Cloud Build and rolls a new revision. Secrets are
# mounted from Secret Manager (run setup-secrets.sh first).
#
# MCP_BASE_URL defaults to the deterministic project-scoped URL
# (https://<service>-<project_number>.<region>.run.app) — the host the OAuth
# client's redirect URI is registered under. Only override it if you know the
# registered redirect URI differs; the legacy *-<hash>-uc.a.run.app alias will
# break sign-in with redirect_uri_mismatch.
#
# Usage:
#     ./infra/deploy.sh

#
# REQUIRED: set PROJECT_ID before running, or edit the default below. The
# default is a placeholder so this script is safe to commit to a public repo.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-your-gcp-project-id}"
SERVICE_NAME="${SERVICE_NAME:-google-maps-mcp}"
REGION="${REGION:-us-central1}"
MCP_BASE_URL="${MCP_BASE_URL:-}"
# GCS bucket persisting FastMCP's OAuth state (client registrations, refresh
# tokens) across instance restarts. Without it, every cold start / deploy
# wipes the in-container store and MCP clients must re-authenticate.
OAUTH_STATE_BUCKET="${OAUTH_STATE_BUCKET:-${PROJECT_ID}-oauth-state}"
OAUTH_STATE_MOUNT="/mnt/oauth-state"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

if ! gcloud storage buckets describe "gs://${OAUTH_STATE_BUCKET}" --project="$PROJECT_ID" &>/dev/null; then
    echo "==> Creating OAuth-state bucket gs://${OAUTH_STATE_BUCKET}..."
    gcloud storage buckets create "gs://${OAUTH_STATE_BUCKET}" \
        --project="$PROJECT_ID" --location="$REGION" \
        --uniform-bucket-level-access >/dev/null
    gcloud storage buckets add-iam-policy-binding "gs://${OAUTH_STATE_BUCKET}" \
        --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
        --role="roles/storage.objectAdmin" >/dev/null
    echo "==> Bucket created and runtime SA granted objectAdmin."
fi

# BCP-47 code all tool results are returned in (translated when needed).
CONNECTOR_LANGUAGE="${CONNECTOR_LANGUAGE:-en}"
# get_route's mode when the user doesn't specify one.
DEFAULT_TRAVEL_MODE="${DEFAULT_TRAVEL_MODE:-TRANSIT}"

env_vars="FASTMCP_HOME=${OAUTH_STATE_MOUNT},CONNECTOR_LANGUAGE=${CONNECTOR_LANGUAGE},DEFAULT_TRAVEL_MODE=${DEFAULT_TRAVEL_MODE}"
# Default to the deterministic project-scoped URL — the same one install.py
# predicts and registers as the OAuth redirect URI. Passing any OTHER host
# (e.g. the legacy random-suffix *.a.run.app alias, which also serves this
# service) makes Google reject sign-in with redirect_uri_mismatch, because
# the server derives its OAuth callback from MCP_BASE_URL.
if [[ -z "$MCP_BASE_URL" ]]; then
    MCP_BASE_URL="https://${SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app"
    echo "==> MCP_BASE_URL not set; defaulting to ${MCP_BASE_URL}"
elif [[ "$MCP_BASE_URL" != "https://${SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app" ]]; then
    echo "WARNING: MCP_BASE_URL=${MCP_BASE_URL} differs from the project-scoped"
    echo "         URL this service's OAuth client was registered with. If Google"
    echo "         sign-in fails with redirect_uri_mismatch, rerun without"
    echo "         overriding MCP_BASE_URL." >&2
fi
env_vars="${env_vars},MCP_BASE_URL=${MCP_BASE_URL}"

echo "==> Project: $PROJECT_ID  Service: $SERVICE_NAME  Region: $REGION"
echo "==> Deploying (Cloud Build will pick up the Dockerfile at the repo root)..."

gcloud run deploy "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --source=. \
    --allow-unauthenticated \
    --port=8080 \
    --memory=2Gi \
    --cpu=2 \
    --timeout=300 \
    --concurrency=4 \
    --max-instances=1 \
    --update-secrets="GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,GOOGLE_OAUTH_CLIENT_ID=GOOGLE_OAUTH_CLIENT_ID:latest,GOOGLE_OAUTH_CLIENT_SECRET=GOOGLE_OAUTH_CLIENT_SECRET:latest,GOOGLE_OAUTH_ALLOWED_EMAILS=GOOGLE_OAUTH_ALLOWED_EMAILS:latest" \
    --add-volume="name=oauth-state,type=cloud-storage,bucket=${OAUTH_STATE_BUCKET}" \
    --add-volume-mount="volume=oauth-state,mount-path=${OAUTH_STATE_MOUNT}" \
    --set-env-vars "$env_vars"

URL=$(gcloud run services describe "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format='value(status.url)')

echo ""
echo "==> Deployed: $URL"
echo "==> MCP endpoint: ${URL}/mcp"
echo "==> OAuth callback to register: ${URL}/auth/callback"
