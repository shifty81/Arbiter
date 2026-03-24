# ─── Arbiter Engine — Docker image (Phase 5 / P5-1) ──────────────────────────
#
# Single-container deployment for the ArbiterEngine FastAPI backend.
# PythonBridge runs in the same container for simplicity.
#
# Usage:
#   docker build -t arbiter-engine .
#   docker run -p 8001:8001 arbiter-engine
#
# Or with docker-compose:
#   docker compose up
#
# The image contains:
#   • ArbiterEngine FastAPI server (port 8001)
#   • PythonBridge FastAPI server  (port 8000)  — optional
#   • All Python dependencies
#
# Data volumes (mount these for persistence):
#   /app/arbiter-config  — .arbiter/ state (api_keys, roles, audit log, workspace state)
#   /app/configs         — user-editable TOML configuration files
#   /app/plugins         — user-installed Arbiter plugins (plugin.json + routes.py)
#   /app/workspace       — projects & workspace files
#   /app/Memory          — archive, library config, conversation logs
#   /app/logs            — session snapshot, self-build telemetry
#
# Environment variables:
#   ARBITER_ENGINE_PORT      Port for ArbiterEngine  (default 8001)
#   ARBITER_BRIDGE_PORT      Port for PythonBridge   (default 8000)
#   OLLAMA_HOST              Ollama server URL        (default http://host.docker.internal:11434)
#   ARBITER_LLM_BACKEND      LLM backend name         (default ollama)
#   ARBITER_LOG_LEVEL        Logging level            (default info)
#   ARBITER_REQUIRE_API_KEY  Set to "true" to enforce API key auth even with no keys registered
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# ── System dependencies ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        patch \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Create unprivileged user ───────────────────────────────────────────────────
RUN groupadd --gid 1001 arbiter \
 && useradd  --uid 1001 --gid arbiter --shell /bin/bash --create-home arbiter

# ── Working directory ──────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies (Engine + Bridge) ─────────────────────────────────────
COPY AIEngine/ArbiterEngine/requirements.txt ./requirements-engine.txt
COPY AIEngine/PythonBridge/requirements.txt  ./requirements-bridge.txt

RUN pip install --no-cache-dir \
        -r requirements-engine.txt \
        -r requirements-bridge.txt \
    && pip install --no-cache-dir \
        uvicorn[standard] \
        fastapi \
        pydantic

# ── Copy application source ────────────────────────────────────────────────────
COPY AIEngine/ArbiterEngine/ ./ArbiterEngine/
COPY AIEngine/PythonBridge/  ./PythonBridge/
COPY roadmap.json             ./roadmap.json

# ── Persistent data directories ───────────────────────────────────────────────
RUN mkdir -p \
        /app/arbiter-config \
        /app/configs \
        /app/plugins \
        /app/workspace \
        /app/Memory/ConversationLogs \
        /app/Memory/archive \
        /app/logs \
        /app/ArbiterEngine/logs \
        /app/ArbiterEngine/workspace \
    && chown -R arbiter:arbiter /app

VOLUME ["/app/arbiter-config", "/app/configs", "/app/plugins", "/app/workspace", "/app/Memory", "/app/logs"]

# ── Switch to unprivileged user ────────────────────────────────────────────────
USER arbiter

# ── Expose ports ──────────────────────────────────────────────────────────────
EXPOSE 8001
EXPOSE 8000

# ── Environment defaults ───────────────────────────────────────────────────────
ENV ARBITER_ENGINE_PORT=8001 \
    ARBITER_BRIDGE_PORT=8000 \
    OLLAMA_HOST=http://host.docker.internal:11434 \
    ARBITER_LLM_BACKEND=ollama \
    ARBITER_LOG_LEVEL=info \
    ARBITER_REQUIRE_API_KEY=false \
    PYTHONUNBUFFERED=1
# Note: OLLAMA_HOST=http://host.docker.internal:11434 is the default for Docker Desktop
# (Windows/macOS). On Linux hosts, override with:
#   docker run -e OLLAMA_HOST=http://172.17.0.1:11434 arbiter-engine
# When using docker-compose with the 'ollama' profile, the service name
# 'ollama' resolves correctly inside the bridge network automatically.

# ── Start script ───────────────────────────────────────────────────────────────
COPY --chown=arbiter:arbiter docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:${ARBITER_ENGINE_PORT}/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
