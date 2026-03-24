#!/usr/bin/env bash
# ─── Arbiter Engine — Docker entry-point (Phase 5 / P5-1) ────────────────────
#
# Starts ArbiterEngine (port 8001) and optionally PythonBridge (port 8000).
# Both servers run in the same container for simplicity; use docker-compose
# to scale them independently if needed.
#
# Volume mounts expected:
#   /app/arbiter-config  → .arbiter/ state (api_keys, roles, audit log)
#   /app/configs         → user config files
#   /app/plugins         → user plugins
# ─────────────────────────────────────────────────────────────────────────────
set -e

ENGINE_PORT="${ARBITER_ENGINE_PORT:-8001}"
BRIDGE_PORT="${ARBITER_BRIDGE_PORT:-8000}"
LOG_LEVEL="${ARBITER_LOG_LEVEL:-info}"

# Symlink /app/ArbiterEngine/.arbiter → /app/arbiter-config volume
# so API key/role/audit state persists across container restarts.
if [ ! -e /app/ArbiterEngine/.arbiter ]; then
    ln -sfn /app/arbiter-config /app/ArbiterEngine/.arbiter
fi

# Symlink /app/ArbiterEngine/configs → /app/configs volume
if [ ! -e /app/ArbiterEngine/configs ]; then
    ln -sfn /app/configs /app/ArbiterEngine/configs
fi

# Symlink /app/ArbiterEngine/plugins → /app/plugins volume
if [ ! -e /app/ArbiterEngine/plugins ]; then
    ln -sfn /app/plugins /app/ArbiterEngine/plugins
fi

echo "──────────────────────────────────────────────────"
echo "  Arbiter Engine  →  http://0.0.0.0:${ENGINE_PORT}"
echo "  PythonBridge    →  http://0.0.0.0:${BRIDGE_PORT}"
echo "  LLM backend     →  ${ARBITER_LLM_BACKEND:-ollama}"
echo "  Ollama host     →  ${OLLAMA_HOST:-http://host.docker.internal:11434}"
echo "  API key auth    →  ${ARBITER_REQUIRE_API_KEY:-false}"
echo "──────────────────────────────────────────────────"

# Start PythonBridge in the background (non-fatal if it fails)
cd /app/PythonBridge
python -m uvicorn fastapi_bridge:app \
    --host 0.0.0.0 \
    --port "${BRIDGE_PORT}" \
    --log-level "${LOG_LEVEL}" &
BRIDGE_PID=$!

# Start ArbiterEngine in the foreground
cd /app/ArbiterEngine
exec python -m uvicorn server:app \
    --host 0.0.0.0 \
    --port "${ENGINE_PORT}" \
    --log-level "${LOG_LEVEL}"
