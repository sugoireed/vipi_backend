#!/usr/bin/env bash
# Start the Vipi engine locally: Risto (llama-server) + the engine API on 127.0.0.1:8100.
# Config comes from engine/.env (see engine/README.md). Ctrl-C stops both.
#
#   engine/run_local.sh
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

RISTO_PORT=${RISTO_PORT:-8080}
RISTO_THREADS=${RISTO_THREADS:-4}
if [ -n "${RISTO_GGUF:-}" ] && ! curl -sf "http://127.0.0.1:$RISTO_PORT/health" >/dev/null; then
  # -ngl 0: CPU only, like a VPS. Use -ngl 99 on a GPU/Apple Silicon machine that isn't busy training.
  llama-server -m "$RISTO_GGUF" --alias risto --jinja -c 2048 --parallel 2 -ngl "${RISTO_GPU_LAYERS:-0}" \
      -t "$RISTO_THREADS" --host 127.0.0.1 --port "$RISTO_PORT" > /tmp/risto-server.log 2>&1 &
  RISTO_PID=$!
  trap 'kill $RISTO_PID 2>/dev/null' EXIT
  until curl -sf "http://127.0.0.1:$RISTO_PORT/health" >/dev/null; do sleep 1; done
  echo "Risto ready on :$RISTO_PORT"
fi

exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port "${ENGINE_PORT:-8100}"
