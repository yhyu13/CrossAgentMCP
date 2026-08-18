"""End-to-end demo runner: boot pool + N simulated agents, run to consensus.

Cross-platform (no shell). Start the pool in-process, create a session with a
shared goal, spawn N `simulated_agent.py` subprocesses, and wait until the
session reaches `satisfied` (or `failed`).

Usage:
    python demo/run_session.py --num-agents 3
"""
from __future__ import annotations

import argparse
import asyncio
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

DEFAULT_GOAL = ("Produce a joint plan every member agrees on. A finished "
                "proposal must contain the token APPROVED.")


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
    ap.add_argument("--num-agents", type=int, default=3)
    ap.add_argument("--goal", default=DEFAULT_GOAL)
    ap.add_argument("--pool-port", type=int, default=0,
                    help="pool port (0 = auto-select free port)")
    ap.add_argument("--token", default="APPROVED")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    store = PoolStore()
    pool_port = args.pool_port or _free_port()
    pool_url = f"http://127.0.0.1:{pool_port}"
    pool_server, pool_task = await _serve_pool(store, pool_port)

    pool = PoolClient(pool_url)
    ok = False
    try:
        session = await pool.create_session(args.goal)
        session_id = session["id"]
        print(f"session {session_id} created")

        procs = []
        for i in range(args.num_agents):
            agent_id = f"agent-{i + 1}"
            port = _free_port()
            cmd = [sys.executable, str(ROOT / "demo" / "simulated_agent.py"),
                   "--id", agent_id, "--pool", pool_url,
                   "--port", str(port), "--session", session_id,
                   "--token", args.token]
            procs.append(asyncio.create_subprocess_exec(
                *cmd, cwd=str(ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT))

        started = await asyncio.gather(*procs)
        print(f"started {len(started)} simulated agents")

        async def _read(p):
            out, _ = await p.communicate()
            return out.decode(errors="replace")

        try:
            outputs = await asyncio.wait_for(
                asyncio.gather(*[_read(p) for p in started]),
                timeout=args.timeout)
        except asyncio.TimeoutError:
            for p in started:
                p.kill()
            print("TIMEOUT waiting for agents")
            outputs = []

        for out in outputs:
            for line in out.splitlines():
                print(f"    {line}")

        st = await pool.session_status(session_id)
        print("\n== final session ==")
        print(f"state       : {st['state']}")
        print(f"iteration   : {st['iteration']}")
        print(f"members     : {st['members']}")
        print(f"satisfaction: {st['satisfaction']}")
        print(f"failedReason: {st.get('failedReason')}")
        print("\n== activity log ==")
        for ev in st["activity"]:
            target = f" -> {ev['targetAgentId']}" if ev.get("targetAgentId") else ""
            print(f"  {ev['seq']:>3} {ev['type']:<18} {ev['agentId']}{target}  {ev['payload'][:60]}")

        ok = st["state"] == "satisfied"
        print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    finally:
        await pool.aclose()
        pool_server.should_exit = True
        await pool_task

    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
