#!/usr/bin/env bash
#
# One-time setup: push the five secrets the Cloud Run service needs to
# Secret Manager, and grant the runtime service account read access.
#
# Reads the OAuth/Maps secrets from mcp_server/.env (so they aren't typed
# into the chat or saved in shell history). The allowed-emails list is
# taken from $ALLOWED_EMAILS or the default below.
#
# Idempotent: re-running adds a NEW VERSION of each secret; older versions
# stay around for rollback. To rotate, just re-run after editing .env.
#
# REQUIRED: set PROJECT_ID and ALLOWED_EMAILS before running, or edit the
# defaults below. The defaults are placeholders so this script is safe to
# commit to a public repo.
#
# Usage:
#     PROJECT_ID=my-gcp-project ALLOWED_EMAILS=me@example.com ./infra/setup-secrets.sh
#     ALLOWED_EMAILS="a@x.com,b@x.com" ./infra/setup-secrets.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-your-gcp-project-id}"
ALLOWED_EMAILS="${ALLOWED_EMAILS:-you@example.com}"
ENV_FILE="${ENV_FILE:-mcp_server/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Run from the repo root." >&2
    exit 1
fi

# Read a key=value line from .env (returns the value with surrounding quotes
# stripped). Stays silent — never prints the value.
read_env() {
    local key="$1"
    local value
    value=$(awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE")
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    if [[ -z "$value" ]]; then
        echo "ERROR: $key not set in $ENV_FILE" >&2
        exit 1
    fi
    printf '%s' "$value"
}

# Create the secret if absent, then push a new version with the given value
# from stdin. Cloud Run reads :latest by default.
upsert_secret() {
    local name="$1"
    if ! gcloud secrets describe "$name" --project="$PROJECT_ID" &>/dev/null; then
        gcloud secrets create "$name" --replication-policy=automatic --project="$PROJECT_ID" >/dev/null
        echo "  created $name"
    fi
    gcloud secrets versions add "$name" --data-file=- --project="$PROJECT_ID" >/dev/null
    echo "  added new version for $name"
}

echo "==> Project: $PROJECT_ID"
echo "==> Pushing secrets..."

read_env GOOGLE_MAPS_API_KEY        | upsert_secret GOOGLE_MAPS_API_KEY
read_env GEMINI_API_KEY             | upsert_secret GEMINI_API_KEY
read_env GOOGLE_OAUTH_CLIENT_ID     | upsert_secret GOOGLE_OAUTH_CLIENT_ID
read_env GOOGLE_OAUTH_CLIENT_SECRET | upsert_secret GOOGLE_OAUTH_CLIENT_SECRET
printf '%s' "$ALLOWED_EMAILS"       | upsert_secret GOOGLE_OAUTH_ALLOWED_EMAILS

# Cloud Run's default runtime service account is <project_number>-compute@.
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "==> Granting roles/secretmanager.secretAccessor to $RUNTIME_SA on each secret..."
for name in GOOGLE_MAPS_API_KEY GEMINI_API_KEY GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET GOOGLE_OAUTH_ALLOWED_EMAILS; do
    gcloud secrets add-iam-policy-binding "$name" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="$PROJECT_ID" \
        --condition=None \
        >/dev/null
    echo "  granted on $name"
done

echo "==> Done. Cloud Run can now read these secrets at deploy time."
