.PHONY: sync test smoke demo down

sync:
	uv sync

test:
	uv run pytest

smoke:
	uv run python smoke.py

demo:
	bash demo/run.sh

down:
	@echo "No daemons persist; run.sh tears down on exit."
