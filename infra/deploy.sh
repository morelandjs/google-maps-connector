#!/usr/bin/env bash
#
# Build + deploy the MCP server to Cloud Run.
#
# Idempotent: each invocation runs `gcloud run deploy --source .`, which
# rebuilds the image via Cloud Build and rolls a new revision. Secrets are
# mounted from Secret Manager (run setup-secrets.sh first).
#
# First deploy:    just run it; the script prints the public URL on success.
# Subsequent runs: pass MCP_BASE_URL with the URL from the first deploy so
#                  the OAuth metadata documents advertise the correct host.
#
# Usage:
#     ./infra/deploy.sh
#     MCP_BASE_URL=https://google-maps-mcp-xyz-uc.a.run.app ./infra/deploy.sh

#
# REQUIRED: set PROJECT_ID before running, or edit the default below. The
# default is a placeholder so this script is safe to commit to a public repo.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-your-gcp-project-id}"
SERVICE_NAME="${SERVICE_NAME:-google-maps-mcp}"
REGION="${REGION:-us-central1}"
MCP_BASE_URL="${MCP_BASE_URL:-}"

env_args=()
if [[ -n "$MCP_BASE_URL" ]]; then
    env_args+=(--set-env-vars "MCP_BASE_URL=${MCP_BASE_URL}")
else
    echo "WARNING: MCP_BASE_URL not set. The first deploy will use the default"
    echo "         (http://localhost:8000) which breaks OAuth from any non-local"
    echo "         client. Re-run this script with MCP_BASE_URL=<the printed URL>"
    echo "         after the first deploy completes." >&2
fi

echo "==> Project: $PROJECT_ID  Service: $SERVICE_NAME  Region: $REGION"
echo "==> Deploying (Cloud Build will pick up the Dockerfile at the repo root)..."

gcloud run deploy "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --source=. \
    --allow-unauthenticated \
    --port=8080 \
    --update-secrets="GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY:latest,GOOGLE_OAUTH_CLIENT_ID=GOOGLE_OAUTH_CLIENT_ID:latest,GOOGLE_OAUTH_CLIENT_SECRET=GOOGLE_OAUTH_CLIENT_SECRET:latest,GOOGLE_OAUTH_ALLOWED_EMAILS=GOOGLE_OAUTH_ALLOWED_EMAILS:latest" \
    ${env_args[@]+"${env_args[@]}"}

URL=$(gcloud run services describe "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format='value(status.url)')

echo ""
echo "==> Deployed: $URL"
echo "==> MCP endpoint: ${URL}/mcp"
echo "==> OAuth callback to register: ${URL}/auth/callback"
