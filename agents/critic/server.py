"""critic — A2A HTTP server on :9102 (peer data-plane endpoint)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from crossagent.a2a import (AgentCard, AgentInterface, AgentSkill, TaskStore,
                            make_app, serve_blocking)

PORT = 9102

CARD = AgentCard(
    name="critic",
    description="Reviews the design doc for correctness and completeness; critiques peers.",
    supportedInterfaces=[AgentInterface(url=f"http://127.0.0.1:{PORT}/")],
    skills=[AgentSkill(id="reviewing", name="reviewing",
                       description="Review design-doc sections for defects.")],
)

if __name__ == "__main__":
    serve_blocking(make_app(CARD, TaskStore()), "127.0.0.1", PORT)
