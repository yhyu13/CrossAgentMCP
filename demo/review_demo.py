"""Autonomous A2A code-review demo: writer/critic/lead review the torchimpulse repo.

Boots the pool + three A2A agent servers in-process (mirroring benchmark.py), then
runs the headless orchestrator with three real ``claude -p`` agents whose shared goal
is to co-author a code review of ``F:\\XD\\git-repo\\torchimpulse`` and converge.

Run:  uv run python demo/review_demo.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from crossagent.a2a import AgentCard, AgentInterface, TaskStore, make_app, run_server
from crossagent.orchestrator import Orchestrator
from crossagent.pool import PoolStore, make_pool_app
from crossagent.pool_client import PoolClient

POOL_PORT = 9100
AGENT_SERVERS = {"writer": 9101, "critic": 9102, "lead": 9103}

# Tokens MUST match agents/*/.mcp.json's pool URL and the bridge's env token. The
# bridge reads CROSSAGENT_POOL_TOKEN from the environment the orchestrator sets.
AGENT_TOKENS = {
    "writer": "demo-writer-token",
    "critic": "demo-critic-token",
    "lead": "demo-lead-token",
}
ORCHESTRATOR_TOKEN = "demo-orchestrator-token"

TARGET_REPO = r"F:\XD\git-repo\torchimpulse"
OUTPUT_PATH = r"F:\XD\git-repo\torchimpulse\A2A_REVIEW.md"

GOAL = (
    "Perform a code review of the Python project at F:\\XD\\git-repo\\torchimpulse and "
    "co-author a single review document at F:\\XD\\git-repo\\torchimpulse\\A2A_REVIEW.md.\n\n"
    "SCOPE: read every .py file under F:\\XD\\git-repo\\torchimpulse\\torchimpulse "
    "(including the p4_interval/ and package_stat/ subpackages), the tests under "
    "F:\\XD\\git-repo\\torchimpulse\\tests, and skim README.md, docs/, web/ and research/ "
    "for context. Ignore data/, P4DailyReports/, __pycache__/ and *.db files.\n\n"
    "The review document MUST contain these sections, in order:\n"
    "1. Overview - what the project does and its main entry points (cli, server, chat, agent).\n"
    "2. Architecture - the modules and how they relate (database.py/models.py, retrieval.py, "
    "server.py, chat.py/agent.py, p4_interval/, package_stat/).\n"
    "3. Strengths.\n"
    "4. Findings by severity (Critical / High / Medium / Low). Every finding must cite a "
    "concrete file:line reference, state the problem, and give a suggested fix.\n"
    "5. Recommendations.\n\n"
    "DIVISION OF LABOR:\n"
    "- writer: draft all sections, reading the source directly so every claim is grounded "
    "in real code with file:line references.\n"
    "- critic: verify the writer's claims against the actual source; post critique_post at "
    "writer (or lead) with concrete corrections (wrong line refs, missed bugs, mis-stated "
    "severity) and add findings the writer missed.\n"
    "- lead: integrate writer + critic into one consistent final document, resolve "
    "disagreements, and give the final sign-off.\n\n"
    "CONVERGENCE RULE: declare_satisfaction(satisfied=true) ONLY when the document is "
    "complete, factually accurate (every finding cites real code), and all three roles "
    "agree there are no remaining defects. Otherwise declare satisfied=false and keep "
    "working.\n\n"
    "Read the source yourself; do not rely on summaries. Work autonomously; do not wait "
    "for a human."
)

AGENTS = [
    {"id": "writer", "role": "writer", "dir": "agents/writer",
     "url": "http://127.0.0.1:9101", "token": "demo-writer-token", "timeoutS": 600},
    {"id": "critic", "role": "critic", "dir": "agents/critic",
     "url": "http://127.0.0.1:9102", "token": "demo-critic-token", "timeoutS": 600},
    {"id": "lead", "role": "lead", "dir": "agents/lead",
     "url": "http://127.0.0.1:9103", "token": "demo-lead-token", "timeoutS": 600},
]


async def _boot_servers() -> list[asyncio.Task]:
    store = PoolStore()
    servers = [run_server(make_pool_app(store, agents=AGENT_TOKENS,
                                        orchestrator_token=ORCHESTRATOR_TOKEN),
                          "127.0.0.1", POOL_PORT)]
    for name, port in AGENT_SERVERS.items():
        card = AgentCard(name=name, description=f"{name} review agent",
                         supportedInterfaces=[AgentInterface(url=f"http://127.0.0.1:{port}/")])
        servers.append(run_server(make_app(card, TaskStore()), "127.0.0.1", port))
    tasks = [asyncio.create_task(s) for s in servers]

    async with httpx.AsyncClient() as c:
        for _ in range(200):
            try:
                if (await c.get(f"http://127.0.0.1:{POOL_PORT}/health")).status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)
    return tasks


async def main() -> None:
    tasks = await _boot_servers()
    try:
        pool = PoolClient(f"http://127.0.0.1:{POOL_PORT}", token=ORCHESTRATOR_TOKEN)
        orch = Orchestrator({"goal": GOAL, "agents": AGENTS, "maxTurns": 9}, pool)
        status = await orch.run()
        await pool.aclose()

        print("\n" + "=" * 72)
        print("[review] final session status:")
        print(json.dumps(status, indent=2))

        try:
            with open(OUTPUT_PATH, encoding="utf-8") as f:
                content = f.read()
            print(f"\n[review] wrote {len(content)} chars to {OUTPUT_PATH}")
        except FileNotFoundError:
            print(f"\n[review] WARNING: {OUTPUT_PATH} was not created")
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
