"""Parametrized agent A2A server.

Configuration via environment variables:
  AGENT_ID          (default "agent")
  AGENT_NAME        (default AGENT_ID)
  AGENT_PORT        (default 9101)
  AGENT_DESCRIPTION (default "")
  AGENT_ROLE        (default "")

The project root is located by walking up to the directory that contains
`shared/`, so this file works both from `agent-template/` and from generated
`agents/<id>/` folders.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in [HERE, *HERE.parents]:
    if (p / "shared" / "__init__.py").exists():
        sys.path.insert(0, str(p))
        break

from shared.a2a import AgentCard, TaskStore, make_app, serve_blocking  # noqa: E402


def main() -> None:
    agent_id = os.environ.get("AGENT_ID", "agent")
    name = os.environ.get("AGENT_NAME", agent_id)
    port = int(os.environ.get("AGENT_PORT", "9101"))
    description = os.environ.get("AGENT_DESCRIPTION", "")
    role = os.environ.get("AGENT_ROLE", "")

    skills = [{
        "id": "chat",
        "name": "chat",
        "description": "Free-form text exchange with peer agents.",
        "tags": ["text"],
    }]
    if role:
        skills.append({"id": "role", "name": "role", "description": role,
                       "tags": ["role"]})

    card = AgentCard(
        name=name,
        description=description or f"A2A pool agent {agent_id}.",
        url=f"http://127.0.0.1:{port}/",
        skills=skills,
    )
    serve_blocking(make_app(card, TaskStore()), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
