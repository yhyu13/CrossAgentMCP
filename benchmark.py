"""Benchmark harness for CrossAgentMCP multi-agent conversations.

Boots the pool + agent A2A servers in-process, then runs a set of test-case
conversations through the headless orchestrator, capturing per-turn and
per-conversation metrics (wall-clock time, token usage, cost) for both real
Claude agents and deterministic stub agents.

Run: uv run python benchmark.py [--case NAME]
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from crossagent.a2a import AgentCard, AgentInterface, TaskStore, make_app, run_server
from crossagent.orchestrator import Orchestrator, claude_argv, kill_process_tree
from crossagent.pool import PoolStore, make_pool_app
from crossagent.pool_client import PoolClient

_PORT_BASE = int(os.environ.get("CROSSAGENT_PORT_BASE", "9100"))
POOL_PORT = _PORT_BASE
AGENT_SERVERS = {"writer": _PORT_BASE + 1, "critic": _PORT_BASE + 2, "lead": _PORT_BASE + 3}
TURN_TIMEOUT_S = 240

# Per-agent bearer tokens + a privileged orchestrator token. The pool enforces
# per-agent identity, so each headless agent presents its own token (threaded via
# CROSSAGENT_POOL_TOKEN) and the orchestrator presents the orchestrator token.
AGENT_TOKENS = {name: secrets.token_hex(8) for name in AGENT_SERVERS}
ORCHESTRATOR_TOKEN = secrets.token_hex(8)


# --------------------------------------------------------------------------- #
# Metrics model
# --------------------------------------------------------------------------- #

@dataclass
class Turn:
    agent: str
    turn: int
    source: str  # "claude" | "stub"
    duration_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class Conversation:
    name: str
    converged: bool = False
    satisfaction: dict[str, Any] = field(default_factory=dict)
    turns: list[Turn] = field(default_factory=list)

    @property
    def n_turns(self) -> int:
        return len(self.turns)

    @property
    def duration_s(self) -> float:
        return sum(t.duration_s for t in self.turns)

    @property
    def input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    @property
    def output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns)

    @property
    def cost_usd(self) -> float:
        return sum(t.cost_usd for t in self.turns)


# --------------------------------------------------------------------------- #
# Agent runners (metric-capturing)
# --------------------------------------------------------------------------- #

def claude_runner_factory(turns: list[Turn]):
    async def runner(agent: dict[str, Any], prompt: str) -> str:
        start = time.perf_counter()
        env = {**os.environ, "CROSSAGENT_POOL_TOKEN": AGENT_TOKENS[agent["id"]]}
        proc = await asyncio.create_subprocess_exec(
            *claude_argv(), "-p",
            "--permission-mode", "bypassPermissions",
            "--output-format", "json",
            prompt,
            cwd=agent["dir"],
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), TURN_TIMEOUT_S)
        except asyncio.TimeoutError:
            await kill_process_tree(proc)
            turns.append(Turn(agent["id"], len(turns), "claude"))
            raise RuntimeError(f"{agent['id']} timed out after {TURN_TIMEOUT_S}s")

        t = Turn(agent=agent["id"], turn=len(turns), source="claude",
                 duration_s=time.perf_counter() - start)
        if proc.returncode == 0 and out.strip():
            data = json.loads(out.decode())
            u = data.get("usage", {})
            t.input_tokens = u.get("input_tokens", 0)
            t.output_tokens = u.get("output_tokens", 0)
            t.cache_read_tokens = u.get("cache_read_input_tokens", 0)
            t.cache_creation_tokens = u.get("cache_creation_input_tokens", 0)
            t.cost_usd = data.get("total_cost_usd", 0.0)
            turns.append(t)
            return data.get("result", "")
        turns.append(t)
        raise RuntimeError(f"{agent['id']} exited {proc.returncode}: {err.decode()[:500]}")

    return runner


def stub_runner_factory(turns: list[Turn], pool: PoolClient, state: dict[str, Any]):
    async def runner(agent: dict[str, Any], prompt: str) -> str:
        start = time.perf_counter()
        await asyncio.sleep(0.05)  # simulate a real turn's work
        output = f"{agent['id']}: reviewed goal, no objections."
        t = Turn(agent=agent["id"], turn=len(turns), source="stub",
                 duration_s=time.perf_counter() - start,
                 # token estimate: ~4 chars/token
                 input_tokens=len(prompt) // 4,
                 output_tokens=len(output) // 4)
        if state["sid"]:
            await pool.declare_satisfaction(state["sid"], agent["id"], True, "stub ok")
        turns.append(t)
        return output

    return runner


# --------------------------------------------------------------------------- #
# Test cases
# --------------------------------------------------------------------------- #

_THREE = [
    {"id": "writer", "role": "writer", "dir": "agents/writer"},
    {"id": "critic", "role": "critic", "dir": "agents/critic"},
    {"id": "lead", "role": "lead", "dir": "agents/lead"},
]
_TWO = _THREE[:2]

CASES: list[dict[str, Any]] = [
    {
        "name": "minimal-2",
        "goal": ("Reach a shared conclusion: for a read-mostly cache, is a hash map "
                 "or a sorted list the better default? Once you agree, declare "
                 "satisfaction. Do not write files."),
        "maxTurns": 4,
        "agents": _TWO,
        "runner": "claude",
    },
    {
        "name": "standard-3",
        "goal": ("Reach genuine three-way consensus on the single best storage design "
                 "for a URL shortener (hash map vs. database-backed KV store vs. "
                 "on-disk index). writer proposes, critic attacks the weaknesses, lead "
                 "integrates into one agreed recommendation. Argue via activity_post "
                 "and critique_post; do not write files. Declare satisfaction only "
                 "when all three endorse the same recommendation."),
        "maxTurns": 9,
        "agents": _THREE,
        "runner": "claude",
    },
    {
        "name": "disagreement-3",
        "goal": ("Reach genuine three-way consensus on whether a payments ledger needs "
                 "strongly-consistent or eventually-consistent storage. writer argues "
                 "for strong consistency, critic challenges it, lead breaks the tie "
                 "with a final defensible ruling. Argue via activity_post and "
                 "critique_post; do not write files. Declare satisfaction only when "
                 "all three truly agree, including the original dissenter."),
        "maxTurns": 9,
        "agents": _THREE,
        "runner": "claude",
    },
    {
        "name": "stub-3",
        "goal": "Deterministic stub baseline (no Claude, token estimates only).",
        "maxTurns": 6,
        "agents": [
            {"id": "writer", "role": "writer"},
            {"id": "critic", "role": "critic"},
            {"id": "lead", "role": "lead"},
        ],
        "runner": "stub",
    },
]


# --------------------------------------------------------------------------- #
# Server boot
# --------------------------------------------------------------------------- #

async def _boot_servers() -> list[asyncio.Task]:
    pool_store = PoolStore()
    servers = [run_server(make_pool_app(pool_store, agents=AGENT_TOKENS,
                                        orchestrator_token=ORCHESTRATOR_TOKEN),
                          "127.0.0.1", POOL_PORT)]
    for name, port in AGENT_SERVERS.items():
        card = AgentCard(name=name, description=name,
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


# --------------------------------------------------------------------------- #
# Run + report
# --------------------------------------------------------------------------- #

async def run_case(case: dict[str, Any], pool: PoolClient) -> Conversation:
    turns: list[Turn] = []
    state: dict[str, Any] = {"sid": None}

    if case["runner"] == "claude":
        runner = claude_runner_factory(turns)
        orch = Orchestrator(case, pool, agent_runner=runner)
        status = await orch.run()
    else:
        runner = stub_runner_factory(turns, pool, state)
        orch = Orchestrator(case, pool, agent_runner=runner)
        state["sid"] = await orch.create_session()
        status = await orch.run()

    return Conversation(name=case["name"], converged=status["allSatisfied"],
                        satisfaction=status.get("satisfaction", {}), turns=turns)


def _fmt(n: Any, unit: str = "") -> str:
    if isinstance(n, float):
        return f"{n:.3f}{unit}"
    return f"{n}{unit}"


def print_report(conversations: list[Conversation]) -> None:
    print("\n" + "=" * 96)
    print("CrossAgentMCP multi-agent conversation benchmark")
    print("=" * 96)
    print(f"{'CASE':<16}{'AG':>3}{'TURNS':>6}{'CONV':>6}{'WALL(s)':>9}"
          f"{'IN_TOK':>10}{'OUT_TOK':>10}{'CACHE_RD':>10}{'COST($)':>10}")
    print("-" * 96)
    for c in conversations:
        print(f"{c.name:<16}{len({t.agent for t in c.turns}):>3}{c.n_turns:>6}"
              f"{'yes' if c.converged else 'no':>6}{c.duration_s:>9.1f}"
              f"{c.input_tokens:>10}{c.output_tokens:>10}"
              f"{sum(t.cache_read_tokens for t in c.turns):>10}{c.cost_usd:>10.4f}")
    print("-" * 96)

    for c in conversations:
        print(f"\n--- {c.name} (per turn) ---")
        print(f"{'turn':>4} {'agent':<8}{'src':<8}{'dur(s)':>8}"
              f"{'in_tok':>8}{'out_tok':>8}{'cost($)':>9}")
        for t in c.turns:
            print(f"{t.turn:>4} {t.agent:<8}{t.source:<8}{t.duration_s:>8.1f}"
                  f"{t.input_tokens:>8}{t.output_tokens:>8}{t.cost_usd:>9.4f}")
        print(f"      satisfaction: {json.dumps(c.satisfaction)}")


async def main() -> None:
    only = None
    if "--case" in sys.argv:
        only = sys.argv[sys.argv.index("--case") + 1]
    cases = [c for c in CASES if only is None or c["name"] == only]
    if not cases:
        print(f"unknown case: {only}")
        return

    tasks = await _boot_servers()
    try:
        pool = PoolClient(f"http://127.0.0.1:{POOL_PORT}", token=ORCHESTRATOR_TOKEN)
        results: list[Conversation] = []
        for case in cases:
            print(f"\n[benchmark] running case: {case['name']}")
            conv = await run_case(case, pool)
            results.append(conv)
            print(f"[benchmark] {case['name']}: converged={conv.converged} "
                  f"turns={conv.n_turns} wall={conv.duration_s:.1f}s "
                  f"cost=${conv.cost_usd:.4f}")
        await pool.aclose()

        print_report(results)
        with open("benchmark-results.json", "w", encoding="utf-8") as f:
            json.dump([{**asdict(c), "input_tokens": c.input_tokens,
                        "output_tokens": c.output_tokens,
                        "cost_usd": c.cost_usd} for c in results], f, indent=2)
        print("\n[benchmark] raw results written to benchmark-results.json")
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
