"""Scripted A2A demo: writer/critic/lead review torchimpulse (no real claude).

Replays the full CrossAgentMCP A2A lifecycle against the live pool + three A2A
servers, using the *real* review findings for torchimpulse as the session content:

    register (per-agent token) -> session -> writer artifact -> critic critique
    -> (satisfaction invalidated) -> writer resolve -> lead integrate
    -> all satisfied -> converged.

Also demonstrates the peer A2A data plane (critic -> writer SendMessage/respond)
and per-agent identity enforcement (a spoofed declare_satisfaction is rejected).

Run:  uv run python demo/review_demo_scripted.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from crossagent.a2a import A2AClient, AgentCard, AgentInterface, TaskStore, make_app, run_server
from crossagent.pool import PoolStore, make_pool_app
from crossagent.pool_client import PoolClient

POOL_PORT = 9100
AGENT_SERVERS = {"writer": 9101, "critic": 9102, "lead": 9103}
AGENT_TOKENS = {
    "writer": "demo-writer-token",
    "critic": "demo-critic-token",
    "lead": "demo-lead-token",
}
ORCHESTRATOR_TOKEN = "demo-orchestrator-token"

GOAL = (
    "Review the Python project at F:\\XD\\git-repo\\torchimpulse and co-author a "
    "single review document at F:\\XD\\git-repo\\torchimpulse\\A2A_REVIEW.md "
    "(Overview / Architecture / Strengths / Findings by severity / Recommendations). "
    "Converge when all three roles agree the review is complete and accurate."
)

# Real findings, used verbatim as session artifacts/critiques.
WRITER_DRAFT = {
    "version": "v1",
    "sections": ["Overview", "Architecture", "Strengths", "Findings", "Recommendations"],
    "findings": [
        {"id": "H1", "sev": "Medium", "ref": "server.py:152",
         "title": "compute_board int() sort can crash on non-numeric change"},
        {"id": "M2", "sev": "Medium", "ref": "retrieval.py:81-97",
         "title": "substring scoring causes false positives (pak~package)"},
        {"id": "M3", "sev": "Medium", "ref": "package_stat/attribution.py:37-45",
         "title": "attributed UPDATE relies on an implicit commit"},
        {"id": "L1", "sev": "Low", "ref": "database.py:237",
         "title": "seed_if_empty injects demo data into any empty DB"},
    ],
}

CRITIQUE = (
    "Draft understates two defects and omits one: "
    "(1) H1 is a full HTTP 500 on malformed records.json, not a Medium - raise to High. "
    "(2) You missed server.py:305 - the in-memory SESSIONS dict is unbounded and "
    "thread-unsafe (sync endpoints run in FastAPI's threadpool); add as High. "
    "(3) Add M4: /api/board|interval|chat have no auth/rate-limit and 'depot' is "
    "user-controlled (server.py:287-320)."
)

LEAD_NOTE = (
    "Integration: agree with critic - H1 and the SESSIONS issue are High. "
    "Keep M2 (retrieval scoring) as Medium. Consolidate into A2A_REVIEW.md and sign off."
)

WRITER_FIX = (
    "Applied critic + lead feedback: H1 raised to High (500 on malformed records.json); "
    "added H2 (SESSIONS unbounded/thread-unsafe) as High; added M4 (unauthenticated "
    "endpoints + user-controlled depot); M2 stays Medium per lead."
)


def _line(tag: str, text: str) -> None:
    print(f"\n[{tag}] {text}")


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
    base = f"http://127.0.0.1:{POOL_PORT}"
    writer = PoolClient(base, token=AGENT_TOKENS["writer"])
    critic = PoolClient(base, token=AGENT_TOKENS["critic"])
    lead = PoolClient(base, token=AGENT_TOKENS["lead"])
    orch = PoolClient(base, token=ORCHESTRATOR_TOKEN)
    try:
        # -- 1. register (per-agent identity) --
        for c, name, url in [(writer, "writer", "http://127.0.0.1:9101"),
                             (critic, "critic", "http://127.0.0.1:9102"),
                             (lead, "lead", "http://127.0.0.1:9103")]:
            await c.register(name, url=url)
        agents = await writer.list_agents()
        _line("1 register", f"{len(agents)} agents in pool: "
                            f"{sorted(a['agentId'] for a in agents)}")

        # -- 2. session --
        s = await orch.session_create(GOAL, members=["writer", "critic", "lead"])
        sid = s["id"]
        _line("2 session", f"created {sid[:8]}... goal set")

        # -- 3. writer drafts (artifact) --
        ev = await writer.post_activity(sid, "writer", "artifact", payload=WRITER_DRAFT)
        _line("3 writer", f"posted review draft v1 (artifact seq={ev['seq']})")

        # -- 4. writer declares satisfied too early (demonstrates the rule) --
        await writer.declare_satisfaction(sid, "writer", True, "draft v1 done")
        st = await orch.session_status(sid)
        _line("4 writer", f"declared satisfied early -> satisfaction={st['satisfaction']}")

        # -- 5. critic watches + critiques (invalidates writer) --
        delta = await critic.activity_since(sid, 0)
        c = await critic.critique(sid, "critic", "writer", CRITIQUE)
        st = await orch.session_status(sid)
        _line("5 critic", f"saw {len(delta)} events; critique #{c['id'][:8]} opened "
                          f"against writer; writer satisfaction reset -> {st['satisfaction']['writer']}")

        # -- 6. auth enforcement: critic cannot speak as writer --
        try:
            await critic.declare_satisfaction(sid, "writer", True, "spoof")
        except httpx.HTTPStatusError as e:
            _line("6 auth", f"spoofed declare_satisfaction rejected (HTTP {e.response.status_code})")

        # -- 7. peer A2A: critic -> writer SendMessage / respond --
        # (A2AClient's URL is the *target*; SendMessage lands in the target's inbox.)
        a2a_writer = A2AClient("http://127.0.0.1:9101")
        sent = await a2a_writer.send_message(
            "from critic: please confirm the line number for the compute_board crash")
        inbox = await a2a_writer.inbox()
        _line("7 peer-A2A", f"critic->writer task {sent['task']['id'][:8]} created; "
                            f"writer inbox has {len(inbox)} pending task")
        await a2a_writer.respond(inbox[0]["id"], "server.py:152")
        _line("7 peer-A2A", "writer responded; task completed")

        # -- 8. writer resolves critique + re-declares --
        await writer.resolve_critique(sid, c["id"], "writer", WRITER_FIX)
        await writer.post_activity(sid, "writer", "artifact",
                                   payload={"version": "v2", "note": "H1->High, +H2 High, +M4, M2 stays Medium"})
        await writer.declare_satisfaction(sid, "writer", True, "v2 fixes applied")

        # -- 9. lead integrates + sign-off --
        await lead.activity_since(sid, 0)
        await lead.post_activity(sid, "lead", "artifact",
                                 payload={"final": "consolidated review written to F:\\XD\\git-repo\\torchimpulse\\A2A_REVIEW.md"})
        await lead.declare_satisfaction(sid, "lead", True, "integrated + signed off")

        # -- 10. critic re-checks + satisfied --
        await critic.activity_since(sid, 0)
        await critic.declare_satisfaction(sid, "critic", True, "no remaining defects")

        # -- 11. convergence --
        st = await orch.session_status(sid)
        _line("11 converge", f"state={st['state']} allSatisfied={st['allSatisfied']} "
                             f"satisfaction={st['satisfaction']} openCritiques={len(st['openCritiques'])} "
                             f"progress={st['progressCount']}/{st['activityCount']}")
        print("\n" + "=" * 72)
        print("final session status:")
        print(json.dumps(st, indent=2))

        await a2a_writer.aclose()
    finally:
        for c in (writer, critic, lead, orch):
            await c.aclose()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
