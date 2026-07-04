# syntax=docker/dockerfile:1.6
#
# Container image for the Google Maps MCP server, targeting Cloud Run.
# - Bind to 0.0.0.0:$PORT (Cloud Run injects PORT)
# - Stateless; secrets come in as env vars from Secret Manager
# - Built via `gcloud run deploy --source .` from the repo root, or
#   locally via `docker build .` (Dockerfile is auto-discovered at root).

FROM python:3.13-slim AS builder

# Faster, deterministic, smaller installs.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY mcp_server/pyproject.toml ./
# Install runtime deps into an isolated prefix that we copy into the final image.
RUN pip install --prefix=/install \
        "fastmcp>=2.3" "httpx>=0.27" "pydantic>=2.6" "python-dotenv>=1.0" \
        "playwright>=1.49" "html2text>=2024.2.26" "pillow>=10.0"

# ---- runtime ----
FROM python:3.13-slim AS runtime

# PLAYWRIGHT_BROWSERS_PATH must be set for BOTH the install below and the
# server at runtime — it puts Chromium in a world-readable path outside
# root's home so the non-root appuser can exec it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Run as non-root for defence in depth.
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# Pull the prepared site-packages tree from the builder stage.
COPY --from=builder /install /usr/local

# Headless Chromium + its OS packages for find_events. --with-deps runs
# apt-get, so this must happen before USER appuser.
RUN playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

# Application code (flat layout — server.py imports the sibling modules).
COPY mcp_server/server.py mcp_server/google_maps.py \
     mcp_server/gemini.py mcp_server/scraper.py mcp_server/events_pipeline.py ./

USER appuser

# Cloud Run injects PORT (typically 8080); the server reads it via os.environ.
# EXPOSE is documentation; Cloud Run doesn't actually need it but it helps
# anyone running the container by hand.
EXPOSE 8080

CMD ["python", "server.py"]
