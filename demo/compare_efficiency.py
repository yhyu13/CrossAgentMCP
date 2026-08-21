"""Head-to-head efficiency comparison: single agent vs the 3-agent A2A pool.

Same question, same model, same machine, same running stack (scripts/start-servers.ps1,
open pool :9100 + agent A2A servers :9101-9103). Runs:

  1. single-agent baseline — ONE ``claude -p`` turn with a fused prompt (all roles).
  2. multi-agent pool      — the 3-agent Orchestrator (writer/critic/lead) round-robin.

Both capture identical per-turn metrics (wall time, input/output/cache tokens, cost)
via ``claude -p --output-format json``, then emit a side-by-side table and the
efficiency ratios. Results are also written to
``demo/output/efficiency_comparison.json``.

Run:  uv run python demo/compare_efficiency.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crossagent.orchestrator import Orchestrator, claude_argv, kill_process_tree
from crossagent.pool_client import PoolClient

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - not a TTY / already reconfigured
    pass

POOL_URL = "http://127.0.0.1:9100"
TURN_TIMEOUT_S = 300
RESULTS_PATH = r"D:\GitRepo-AI\CrossAgentMCP\demo\output\efficiency_comparison.json"

QUESTION = (
    "For a payments ledger, is strongly-consistent or eventually-consistent "
    "storage the right default?"
)

# Multi-agent goal (the Orchestrator's _prompt wraps this into per-turn prompts).
GOAL_MULTI = (
    "Reach genuine three-way consensus on whether a payments ledger needs "
    "strongly-consistent or eventually-consistent storage. writer argues for strong "
    "consistency, critic challenges it, lead breaks the tie with a final defensible "
    "ruling. Argue via activity_post and critique_post; do not write files. Declare "
    "satisfaction only when all three truly agree, including the original dissenter."
)

# Single-agent fused prompt (all three roles collapsed into one turn).
PROMPT_SINGLE = (
    "You are a senior distributed-systems engineer.\n\n"
    f"Question: {QUESTION}\n\n"
    "Do the following in one pass:\n"
    "1. Steelman the STRONG-consistency case (best argument for it).\n"
    "2. Steelman the EVENTUAL-consistency case (best argument for it).\n"
    "3. Deliver a final, defensible ruling with concrete reasoning and the key "
    "tradeoffs.\n"
    "Be thorough but concise. End with the final ruling."
)

AGENTS = [
    {"id": "writer", "role": "writer", "dir": "D:/GitRepo-AI/CrossAgentMCP/agents/writer",
     "url": "http://127.0.0.1:9101", "timeoutS": TURN_TIMEOUT_S},
    {"id": "critic", "role": "critic", "dir": "D:/GitRepo-AI/CrossAgentMCP/agents/critic",
     "url": "http://127.0.0.1:9102", "timeoutS": TURN_TIMEOUT_S},
    {"id": "lead", "role": "lead", "dir": "D:/GitRepo-AI/CrossAgentMCP/agents/lead",
     "url": "http://127.0.0.1:9103", "timeoutS": TURN_TIMEOUT_S},
]


@dataclass
class Turn:
    agent: str
    turn: int
    duration_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class Run:
    mode: str
    converged: bool = False
    turns: list[Turn] = field(default_factory=list)

    @property
    def n_turns(self) -> int:
        return len(self.turns)

    @property
    def wall_s(self) -> float:
        return sum(t.duration_s for t in self.turns)

    @property
    def input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    @property
    def output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns)

    @property
    def cache_read_tokens(self) -> int:
        return sum(t.cache_read_tokens for t in self.turns)

    @property
    def cost_usd(self) -> float:
        return sum(t.cost_usd for t in self.turns)


async def _run_claude_json(prompt: str, cwd: str, timeout_s: float) -> tuple[dict, str]:
    """One `claude -p` turn; returns (usage_dict, result_text)."""
    proc = await asyncio.create_subprocess_exec(
        *claude_argv(), "-p",
        "--permission-mode", "bypassPermissions",
        "--output-format", "json",
        prompt,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
    except asyncio.TimeoutError:
        await kill_process_tree(proc)
        raise RuntimeError("claude timed out")
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {err.decode(errors='replace')[:500]}")
    data = json.loads(out.decode(errors="replace"))
    return data.get("usage", {}), data.get("result", ""), data.get("total_cost_usd", 0.0)


async def run_single() -> Run:
    run = Run(mode="single-agent")
    start = time.perf_counter()
    usage, result, cost = await _run_claude_json(
        PROMPT_SINGLE, "D:/GitRepo-AI/CrossAgentMCP", TURN_TIMEOUT_S)
    run.turns.append(Turn(
        agent="single", turn=0, duration_s=time.perf_counter() - start,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        cost_usd=cost,
    ))
    run.converged = bool(result.strip())
    return run


def make_multi_runner(turns: list[Turn]):
    async def runner(agent: dict[str, Any], prompt: str) -> str:
        start = time.perf_counter()
        try:
            usage, result, cost = await _run_claude_json(
                prompt, agent["dir"], float(agent.get("timeoutS", TURN_TIMEOUT_S)))
        except Exception as e:  # noqa: BLE001
            turns.append(Turn(agent=agent["id"], turn=len(turns)))
            raise RuntimeError(f"{agent['id']}: {e}") from e
        turns.append(Turn(
            agent=agent["id"], turn=len(turns),
            duration_s=time.perf_counter() - start,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cost_usd=cost,
        ))
        return result
    return runner


async def run_multi(pool: PoolClient) -> Run:
    turns: list[Turn] = []
    orch = Orchestrator({"goal": GOAL_MULTI, "agents": AGENTS, "maxTurns": 9},
                        pool, agent_runner=make_multi_runner(turns))
    await orch.register_all()
    await orch.create_session()
    status = await orch.run()
    run = Run(mode="3-agent", converged=bool(status["allSatisfied"]), turns=turns)
    return run


def _table(single: Run, multi: Run) -> str:
    def row(name, r):
        return (f"{name:<14}{r.n_turns:>6}{r.wall_s:>10.1f}{r.input_tokens:>10}"
                f"{r.output_tokens:>10}{r.cache_read_tokens:>12}{r.cost_usd:>10.4f}")
    lines = [
        "=" * 92,
        f"Efficiency comparison — {QUESTION}",
        "=" * 92,
        f"{'MODE':<14}{'TURNS':>6}{'WALL(s)':>10}{'IN_TOK':>10}{'OUT_TOK':>10}"
        f"{'CACHE_RD':>12}{'COST($)':>10}",
        "-" * 92,
        row("single-agent", single),
        row("3-agent", multi),
        "-" * 92,
    ]
    if single.n_turns and single.cost_usd:
        lines.append(f"overhead: turns x{multi.n_turns/single.n_turns:.1f}, "
                     f"wall x{multi.wall_s/single.wall_s:.2f}, "
                     f"in_tok x{multi.input_tokens/single.input_tokens:.2f}, "
                     f"cost x{multi.cost_usd/single.cost_usd:.2f}")
    lines.append(f"converged -> single={single.converged}, multi={multi.converged}")
    return "\n".join(lines)


async def main() -> None:
    print(f"[compare] model: {__import__('os').environ.get('ANTHROPIC_MODEL', '(inherit)')}")
    print("[compare] running single-agent baseline ...")
    single = await run_single()
    print(f"[compare] single done: {single.n_turns} turn, {single.wall_s:.1f}s, "
          f"${single.cost_usd:.4f}")

    pool = PoolClient(POOL_URL)
    try:
        print("[compare] running 3-agent pool ...")
        multi = await run_multi(pool)
    finally:
        await pool.aclose()
    print(f"[compare] multi done: {multi.n_turns} turns, {multi.wall_s:.1f}s, "
          f"${multi.cost_usd:.4f}, converged={multi.converged}")

    table = _table(single, multi)
    print("\n" + table)

    payload = {
        "question": QUESTION,
        "single": {"turns": [t.__dict__ for t in single.turns],
                   "totals": {"wall_s": single.wall_s, "input_tokens": single.input_tokens,
                              "output_tokens": single.output_tokens,
                              "cache_read_tokens": single.cache_read_tokens,
                              "cost_usd": single.cost_usd}},
        "multi": {"turns": [t.__dict__ for t in multi.turns],
                  "totals": {"wall_s": multi.wall_s, "input_tokens": multi.input_tokens,
                             "output_tokens": multi.output_tokens,
                             "cache_read_tokens": multi.cache_read_tokens,
                             "cost_usd": multi.cost_usd}},
    }
    out = Path(RESULTS_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n[compare] results written to {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
