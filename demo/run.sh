#!/usr/bin/env bash
# Boot pool -> agents -> orchestrator, headless, then tear down.
set -euo pipefail
cd "$(dirname "$0")/.."

POOL_PORT=9100
AGENT_PORTS=(9101 9102 9103)

uv sync --quiet

pids=()
cleanup() {
  for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done
}
trap cleanup EXIT

echo "[demo] starting pool on :$POOL_PORT"
# Per-agent tokens + orchestrator token MUST match demo/goal.json (the orchestrator
# threads each agent's token via CROSSAGENT_POOL_TOKEN and reads orchestratorToken).
uv run python -m crossagent.pool --host 127.0.0.1 --port "$POOL_PORT" \
  --agents '{"writer":"demo-writer-token","critic":"demo-critic-token","lead":"demo-lead-token"}' \
  --orchestrator-token demo-orchestrator-token &
pids+=($!)

echo "[demo] starting agent A2A servers"
uv run python agents/writer/server.py &
pids+=($!)
uv run python agents/critic/server.py &
pids+=($!)
uv run python agents/lead/server.py &
pids+=($!)

echo "[demo] waiting for pool health"
for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$POOL_PORT/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done

echo "[demo] running orchestrator"
uv run python -m crossagent.orchestrator demo/goal.json

echo "[demo] done"
