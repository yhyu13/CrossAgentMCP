"""Run a REAL multi-agent review session through the A2A pool.

Unlike `simulated_agent.py` (deterministic token game, no LLM), this driver
plays back outputs produced by real LLM agents (subagents that actually read
the target repo and critique each other) through the pool's control-plane FSM:

    register -> join -> started -> finished(findings v1)
    -> critique(peer) -> resolve(self-improved, findings v2) -> finished(v2)
    -> satisfy -> session-completed

The payload (produced upstream by the real agents) has this shape:

    {
      "goal": "...",
      "agents": [
        {"id", "role", "findings", "critique_of", "critique_text", "revised"}
      ]
    }

Each agent may carry an optional `critique_of`/`critique_text` pair (its
critique of a peer) and an optional `revised` (its self-improved findings in
response to the critique it received).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in [ROOT]:
    sys.path.insert(0, str(p))

import uvicorn  # noqa: E402

from pool.coordinator import make_coordinator  # noqa: E402
from pool.store import PoolStore  # noqa: E402
from shared.pool_client import PoolClient  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _serve_pool(store: PoolStore, port: int) -> tuple[uvicorn.Server, asyncio.Task]:
    app = make_coordinator(store)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    return server, task


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True,
                    help="JSON file with goal + agents (findings/critique/revised)")
    args = ap.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    goal = payload["goal"]
    agents = payload["agents"]

    store = PoolStore()
    pool_port = _free_port()
    pool_url = f"http://127.0.0.1:{pool_port}"
    pool_server, pool_task = await _serve_pool(store, pool_port)

    pool = PoolClient(pool_url)
    try:
        session = await pool.create_session(goal)
        sid = session["id"]
        print(f"session {sid} created")
        print(f"goal: {goal}\n")

        # register + join + started
        for a in agents:
            url = f"http://127.0.0.1:{_free_port()}"
            await pool.register(a["id"],
                                {"name": a["id"], "description": a.get("role", "")},
                                url)
            await pool.join_session(sid, a["id"])
            await pool.post_activity(sid, a["id"], "started",
                                     text=f"{a['id']} started ({a.get('role', '')})")

        # finished (findings v1)
        for a in agents:
            await pool.post_activity(sid, a["id"], "finished", text=a["findings"])

        # critique round: each agent critiques its designated peer
        crit_ids: dict[str, str] = {}  # target agent id -> critique thread id
        for a in agents:
            tgt = a.get("critique_of")
            if not tgt:
                continue
            thread = await pool.critique_send(sid, a["id"], tgt, a["critique_text"])
            crit_ids[tgt] = thread["id"]

        # resolve round: each critiqued agent self-improves, then re-finishes
        for a in agents:
            cid = crit_ids.get(a["id"])
            if not cid:
                continue
            await pool.critique_resolve(sid, cid, a["id"], a["revised"])
            await pool.post_activity(sid, a["id"], "finished", text=a["revised"])

        # convergence: every agent declares satisfaction
        for a in agents:
            await pool.declare_satisfaction(sid, a["id"])

        st = await pool.session_status(sid)
        print("== final session ==")
        print(f"state       : {st['state']}")
        print(f"iteration   : {st['iteration']}")
        print(f"members     : {st['members']}")
        print(f"satisfaction: {st['satisfaction']}")
        print(f"failedReason: {st.get('failedReason')}")
        print("\n== activity log ==")
        for ev in st["activity"]:
            tgt = f" -> {ev['targetAgentId']}" if ev.get("targetAgentId") else ""
            print(f"  {ev['seq']:>3} {ev['type']:<18} {ev['agentId']}{tgt}  {ev['payload'][:70]}")
        ok = st["state"] == "satisfied"
        print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
        raise SystemExit(0 if ok else 1)
    finally:
        await pool.aclose()
        pool_server.should_exit = True
        await pool_task


if __name__ == "__main__":
    asyncio.run(main())
