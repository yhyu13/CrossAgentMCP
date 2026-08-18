"""Generate a concrete agent folder from `agent-template/`.

Usage:
    python make_agent.py --id agent-1 --port 9101 --role "writes section 1"

Produces `agents/<id>/` with server.py (verbatim), CLAUDE.md and .mcp.json
(with placeholders substituted). PROJECT_ROOT is embedded as an absolute path.
"""
from __future__ import annotations

import argparse
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent
ROOT = TEMPLATE.parent
POOL_PORT = "9100"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, dest="agent_id")
    ap.add_argument("--name", default=None)
    ap.add_argument("--port", required=True, type=int)
    ap.add_argument("--role", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--pool-url", default=f"http://127.0.0.1:{POOL_PORT}")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    name = args.name or args.agent_id
    local_url = f"http://127.0.0.1:{args.port}"
    out = Path(args.out) if args.out else ROOT / "agents" / args.agent_id
    out.mkdir(parents=True, exist_ok=True)

    (out / "server.py").write_text(
        (TEMPLATE / "server.py").read_text(encoding="utf-8"), encoding="utf-8")

    def render(tpl: str) -> str:
        return (tpl
                .replace("{ROOT}", str(ROOT))
                .replace("{NAME}", name)
                .replace("{SELF_ID}", args.agent_id)
                .replace("{POOL_URL}", args.pool_url)
                .replace("{LOCAL_URL}", local_url)
                .replace("{AGENT_ID}", args.agent_id)
                .replace("{AGENT_ROLE}", args.role or "general collaborator"))

    (out / "CLAUDE.md").write_text(
        render((TEMPLATE / "CLAUDE.md").read_text(encoding="utf-8")),
        encoding="utf-8")
    (out / ".mcp.json").write_text(
        render((TEMPLATE / ".mcp.json").read_text(encoding="utf-8")),
        encoding="utf-8")

    print(f"created {out}")
    print(f"\nBoot its A2A server FIRST (separate terminal), otherwise "
          f"agentpool_inbox / agentpool_respond will fail:")
    print(f"  set AGENT_PORT={args.port}")
    print(f"  uv run python agents/{args.agent_id}/server.py")
    print(f"\nThen start the agent:")
    print(f"  cd agents/{args.agent_id} && claude")


if __name__ == "__main__":
    main()
