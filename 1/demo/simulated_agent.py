"""Deterministic simulated pool agent — exercises the full autonomous loop with no LLM.

Each agent:
  1. starts a local A2A server,
  2. registers with the pool,
  3. joins a session,
  4. posts a deliberately-flawed `finished` proposal (missing the required token),
  5. critiques peers whose proposal is flawed,
  6. self-improves when critiqued (adds the token) and re-finishes,
  7. declares satisfaction only when its own output AND every peer's output are good.

The session converges to `satisfied` when all members approve and no critique
threads are open. This is the same loop a real Claude Code agent runs via the
MCP bridge; here it is deterministic and needs no model.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in [HERE, *HERE.parents]:
    if (p / "shared" / "__init__.py").exists():
        sys.path.insert(0, str(p))
        break

import uvicorn  # noqa: E402

from shared.a2a import AgentCard, TaskStore, make_app  # noqa: E402
from shared.pool_client import PoolClient  # noqa: E402

REQUIRED_TOKEN = "APPROVED"


async def _serve_local(port: int) -> tuple[uvicorn.Server, asyncio.Task]:
    app = make_app(AgentCard(name=f"agent-{port}", description="simulated",
                             url=f"http://127.0.0.1:{port}/"), TaskStore())
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    return server, task


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, dest="agent_id")
    ap.add_argument("--pool", default="http://127.0.0.1:9100")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--token", default=REQUIRED_TOKEN)
    ap.add_argument("--rounds", type=int, default=1,
                    help="DRAFT rounds before self-correcting to the token")
    ap.add_argument("--block", action="store_true",
                    help="post `blocked` instead of a finished proposal")
    ap.add_argument("--leave-after-finish", action="store_true",
                    help="leave the session right after the first finished")
    args = ap.parse_args()

    token = args.token
    local_url = f"http://127.0.0.1:{args.port}"
    local_server, server_task = await _serve_local(args.port)

    pool = PoolClient(args.pool)
    try:
        card = {"name": args.agent_id, "description": "simulated pool agent",
                "url": local_url}
        await pool.register(args.agent_id, card, local_url)
        await pool.join_session(args.session, args.agent_id)

        # wait until the session starts working (goal set + >=2 members)
        for _ in range(100):
            st = await pool.session_status(args.session)
            if st["state"] in ("working", "reviewing", "satisfied", "failed"):
                break
            await asyncio.sleep(0.2)
        else:
            print(f"{args.agent_id}: session never started", file=sys.stderr)
            return

        await pool.post_activity(args.session, args.agent_id, "started",
                                 text=f"{args.agent_id} started")

        # Initial (flawed) proposal: does NOT contain the required token.
        my_proposal = f"proposal from {args.agent_id}: DRAFT v0"

        if args.block:
            await pool.post_activity(args.session, args.agent_id, "blocked",
                                     text=f"{args.agent_id} cannot proceed")
            print(f"{args.agent_id}: blocked")
            return

        await pool.post_activity(args.session, args.agent_id, "finished",
                                 text=my_proposal)
        if args.leave_after_finish:
            await pool.leave_session(args.session, args.agent_id)
            print(f"{args.agent_id}: left after finish")
            return
        seq = 0  # watch from the start so we never miss a peer's earlier post

        peer_versions: dict[str, str] = {}
        critiqued: dict[str, str] = {}
        declared = False
        round_num = 0

        def maybe_declare(members: list[str]) -> bool:
            nonlocal declared
            if token not in my_proposal or declared:
                return False
            for m in members:
                if m == args.agent_id:
                    continue
                v = peer_versions.get(m)
                if not v or token not in v:
                    return False
            return True

        while True:
            st = await pool.session_status(args.session)
            if st["state"] == "satisfied":
                print(f"{args.agent_id}: DONE satisfied")
                return
            if st["state"] == "failed":
                print(f"{args.agent_id}: DONE failed: {st.get('failedReason')}")
                return
            members = st["members"]

            events = []

            async def _collect() -> None:
                async for ev in pool.activity_subscribe(args.session, seq):
                    events.append(ev)

            try:
                await asyncio.wait_for(_collect(), timeout=2.0)
            except Exception:  # noqa: BLE001 — timeout OR transient SSE drop; retry next poll
                pass
            for ev in events:
                seq = max(seq, ev["seq"] + 1)
                t = ev["type"]
                if t == "critique" and ev.get("targetAgentId") == args.agent_id:
                    declared = False
                    round_num += 1
                    if token not in my_proposal:
                        if round_num >= args.rounds:
                            my_proposal = f"proposal from {args.agent_id}: {token}"
                        else:
                            my_proposal = (f"proposal from {args.agent_id}: "
                                           f"DRAFT v{round_num}")
                    await pool.critique_resolve(args.session, ev["critiqueId"],
                                                args.agent_id, my_proposal)
                    await pool.post_activity(args.session, args.agent_id,
                                             "finished", text=my_proposal)
                elif t == "finished" and ev.get("agentId") != args.agent_id:
                    peer_versions[ev["agentId"]] = ev["payload"]
                    if (token not in ev["payload"]
                            and critiqued.get(ev["agentId"]) != ev["payload"]):
                        critiqued[ev["agentId"]] = ev["payload"]
                        await pool.critique_send(args.session, args.agent_id,
                                                 ev["agentId"],
                                                 f"please add {token} to your proposal")
                elif t == "session-completed":
                    print(f"{args.agent_id}: DONE satisfied")
                    return
                elif t == "session-failed":
                    print(f"{args.agent_id}: DONE failed: {ev.get('payload')}")
                    return

            if maybe_declare(members):
                await pool.declare_satisfaction(args.session, args.agent_id)
                declared = True

            # bounded watch: if no new events arrive quickly, poll again
            await asyncio.sleep(0.1)
    finally:
        local_server.should_exit = True
        await server_task
        await pool.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
