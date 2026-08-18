"""writer — A2A HTTP server on :9101 (peer data-plane endpoint)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from crossagent.a2a import (AgentCard, AgentInterface, AgentSkill, TaskStore,
                            make_app, serve_blocking)

PORT = 9101

CARD = AgentCard(
    name="writer",
    description="Drafts the shared design doc and revises it on critiques from critic and lead.",
    supportedInterfaces=[AgentInterface(url=f"http://127.0.0.1:{PORT}/")],
    skills=[AgentSkill(id="drafting", name="drafting",
                       description="Write and revise design-doc sections.")],
)

if __name__ == "__main__":
    serve_blocking(make_app(CARD, TaskStore()), "127.0.0.1", PORT)
