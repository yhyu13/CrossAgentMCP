"""Benchmark: run a set of multi-agent conversation scenarios and report metrics.

Each scenario is one full session (one "conversation"). The runner boots the pool
in-process, spawns N simulated agents (subprocesses), waits for the session to
finish, then computes token/timing metrics from the activity log.

Usage:
    uv run python demo/benchmark.py            # all scenarios
    uv run python demo/benchmark.py --only converge-3
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from demo.metrics import compute_session_metrics  # noqa: E402
from pool.coordinator import make_coordinator  # noqa: E402
from pool.store import PoolStore  # noqa: E402
from shared.pool_client import PoolClient  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

GOAL = ("Produce a joint plan every member agrees on. A finished proposal must "
        "contain the token APPROVED.")

# name -> scenario config ("expect" = terminal state the scenario is designed to hit)
SCENARIOS = [
    {"name": "converge-3", "agents": 3, "expect": "satisfied"},
    {"name": "converge-5", "agents": 5, "expect": "satisfied"},
    {"name": "converge-8", "agents": 8, "expect": "satisfied"},
    {"name": "contentious-3r", "agents": 3, "rounds": 3, "expect": "satisfied"},
    {"name": "blocked-3", "agents": 3, "block_idx": 0, "expect": "failed"},
    {"name": "member-leave-3", "agents": 3, "leave_idx": 1, "expect": "failed"},
    {"name": "max-iterations-3", "agents": 3, "maxIterations": 3, "expect": "failed"},
]


async def _serve_pool(store: PoolStore, port: int) -> tuple[uvicorn.Server, asyncio.Task]:
    app = make_coordinator(store)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    return server, task


async def run_one(scn: dict, pool_port: int, timeout: float) -> dict:
    store = PoolStore()
    pool_url = f"http://127.0.0.1:{pool_port}"
    server, task = await _serve_pool(store, pool_port)
    pool = PoolClient(pool_url)
    try:
        session = await pool.create_session(GOAL)
        sid = session["id"]
        if "maxIterations" in scn:
            store.get_session(sid).maxIterations = scn["maxIterations"]

        n = scn["agents"]
        rounds = scn.get("rounds", 1)
        block_idx = scn.get("block_idx", -1)
        leave_idx = scn.get("leave_idx", -1)

        procs = []
        for i in range(n):
            agent_id = f"agent-{i + 1}"
            cmd = [sys.executable, str(ROOT / "demo" / "simulated_agent.py"),
                   "--id", agent_id, "--pool", pool_url,
                   "--port", str(_free_port()), "--session", sid]
            if rounds != 1:
                cmd += ["--rounds", str(rounds)]
            if i == block_idx:
                cmd += ["--block"]
            if i == leave_idx:
                cmd += ["--leave-after-finish"]
            procs.append(asyncio.create_subprocess_exec(
                *cmd, cwd=str(ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT))

        started = await asyncio.gather(*procs)

        async def _read(p):
            out, _ = await p.communicate()
            return out.decode(errors="replace")

        outputs = []
        try:
            outputs = await asyncio.wait_for(
                asyncio.gather(*[_read(p) for p in started]), timeout=timeout)
        except asyncio.TimeoutError:
            for p in started:
                p.kill()

        st = await pool.session_status(sid)
        m = compute_session_metrics(st)
        m["name"] = scn["name"]
        m["_agent_output"] = outputs
        return m
    finally:
        await pool.aclose()
        server.should_exit = True
        await task


def _fmt_row(name, m):
    ttt = m["time_to_terminal_sec"]
    ttff = m["time_to_first_finished_sec"]
    acr = m["avg_critique_resolve_sec"]
    fail = m["failedReason"] or ""
    return (f"{name:<18} {m['members']:>3} {m['state']:<9} "
            f"{m.get('expect', '-'):<9} "
            f"{m['iterations']:>3} {m['critiques']:>4} {m['self_improvements']:>5} "
            f"{m['events']:>4} {m['tokens_est']:>7} "
            f"{m['wall_sec']:>8} {ttt if ttt is not None else '-':>8} "
            f"{ttff if ttff is not None else '-':>8} "
            f"{acr if acr is not None else '-':>7}  {fail}")


def _print_agent_breakdown(name, m):
    print(f"\n== per-agent breakdown: {name} ==")
    print(f"{'agent':<9} {'events':>6} {'tokens':>6} {'crit_given':>10} "
          f"{'crit_recv':>9} {'improved':>8} {'finished':>8} {'active_s':>9}")
    for a in m["per_agent"]:
        print(f"{a['agentId']:<9} {a['events']:>6} {a['tokens_out']:>6} "
              f"{a['critiques_sent']:>10} {a['critiques_received']:>9} "
              f"{a['self_improvements']:>8} {a['finished']:>8} {a['active_sec']:>9}")


async def amain(args) -> None:
    scns = SCENARIOS
    if args.only:
        scns = [s for s in SCENARIOS if s["name"] in args.only.split(",")]

    header = (f"{'scenario':<18} {'N':>3} {'state':<9} {'exp':<9} {'it':>3} {'crit':>4} "
              f"{'impro':>5} {'ev':>4} {'tokens':>7} {'wall_s':>8} "
              f"{'to_end':>8} {'to_1st':>8} {'avgCR':>7}  reason")
    print("token figures are estimates (~4 chars/token) over activity payloads\n")
    print(header)
    print("-" * len(header))

    results = []
    passed = 0
    pool_port = args.pool_port or _free_port()
    for scn in scns:
        print(f"running {scn['name']} ...", file=sys.stderr)
        m = await run_one(scn, pool_port, args.timeout)
        ok = m["state"] == scn.get("expect")
        passed += 1 if ok else 0
        m["expect"] = scn.get("expect")
        results.append((scn["name"], m))
        print(_fmt_row(scn["name"], m) + ("" if ok else "   ** MISMATCH **"))

    print(f"\n{passed}/{len(scns)} scenarios reached their expected terminal state")

    if args.detail:
        for name, m in results:
            _print_agent_breakdown(name, m)

    if args.verbose:
        for name, m in results:
            for out in m.get("_agent_output", []):
                for line in out.splitlines():
                    if line.strip():
                        print(f"[{name}] {line}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated scenario names")
    ap.add_argument("--detail", action="store_true", help="print per-agent breakdown")
    ap.add_argument("--verbose", action="store_true", help="print agent stdout/stderr")
    ap.add_argument("--pool-port", type=int, default=0,
                    help="pool port (0 = auto-select free port)")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
