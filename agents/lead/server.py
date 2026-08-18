"""lead — A2A HTTP server on :9103 (peer data-plane endpoint)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from crossagent.a2a import (AgentCard, AgentInterface, AgentSkill, TaskStore,
                            make_app, serve_blocking)

PORT = 9103

CARD = AgentCard(
    name="lead",
    description="Integrates sections, resolves disputes, and does final sign-off on the doc.",
    supportedInterfaces=[AgentInterface(url=f"http://127.0.0.1:{PORT}/")],
    skills=[AgentSkill(id="integration", name="integration",
                       description="Integrate and sign off the design doc.")],
)

if __name__ == "__main__":
    serve_blocking(make_app(CARD, TaskStore()), "127.0.0.1", PORT)
