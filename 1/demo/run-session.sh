#!/usr/bin/env bash
# End-to-end autonomous session demo (bash wrapper around run_session.py).
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python demo/run_session.py "$@"
