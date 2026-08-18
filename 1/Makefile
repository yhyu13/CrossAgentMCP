.PHONY: install test demo pool up down

install:
	uv sync

test:
	uv run pytest

demo:
	uv run python demo/run_session.py --num-agents 3

pool:
	uv run python -m pool.server

# Convenience (Unix/macOS): boot pool + 3 agents headlessly.
up:
	uv run python demo/run_session.py --num-agents 3

down:
	@echo "sessions stop when their runner exits; pool is a child of run_session.py"
