"""Full efficiency + quality comparison: single-agent (monolithic & iterative) vs 3-agent pool.

Same question, same model, same machine, same running stack. Runs three modes:

  1. single-monolithic  — one ``claude -p`` turn, fused prompt (all roles).
  2. single-iterative   — one agent self-reviewing for N turns, where N equals the
                           number of turns the 3-agent pool actually took to converge.
  3. 3-agent pool       — the Orchestrator (writer/critic/lead) round-robin.

Each mode captures identical per-turn metrics (wall time, input/output/cache tokens,
cost). The final answer of each mode is then scored by an independent, blind second
judge against a 5-criterion rubric (max 25), so the comparison reports quality_delta
and cost-per-point — not just raw tokens. Judge cost is recorded separately and NOT
folded into the mode's own cost.

Run:  uv run python demo/compare_quality.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
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
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = r"D:\GitRepo-AI\CrossAgentMCP"
POOL_URL = "http://127.0.0.1:9100"
TURN_TIMEOUT_S = 300
JUDGE_TIMEOUT_S = 120
RESULTS_PATH = r"D:\GitRepo-AI\CrossAgentMCP\demo\output\quality_comparison.json"

QUESTION = (
    "For a payments ledger, is strongly-consistent or eventually-consistent "
    "storage the right default?"
)

GOAL_MULTI = (
    "Reach genuine three-way consensus on whether a payments ledger needs "
    "strongly-consistent or eventually-consistent storage. writer argues for strong "
    "consistency, critic challenges it, lead breaks the tie with a final defensible "
    "ruling. Argue via activity_post and critique_post; do not write files. Declare "
    "satisfaction only when all three truly agree, including the original dissenter."
)

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
    final_answer: str = ""
    judge: dict = field(default_factory=dict)

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


async def _run_claude_json(prompt: str, cwd: str, timeout_s: float):
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


async def run_single_monolithic() -> Run:
    run = Run(mode="single-monolithic")
    start = time.perf_counter()
    usage, result, cost = await _run_claude_json(PROMPT_SINGLE, ROOT_DIR, TURN_TIMEOUT_S)
    run.turns.append(Turn(
        agent="single", turn=0, duration_s=time.perf_counter() - start,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        cost_usd=cost,
    ))
    run.final_answer = result.strip()
    run.converged = bool(run.final_answer)
    return run


async def run_single_iterative(rounds: int) -> Run:
    run = Run(mode=f"single-iterative({rounds})")
    answer = ""
    for i in range(rounds):
        prompt = PROMPT_SINGLE if i == 0 else (
            f"Here is your current draft answer to the question '{QUESTION}':\n\n"
            f"{answer}\n\n"
            "Critique it rigorously and produce a strictly better revised answer. "
            "Keep the structure (steelman both sides, then rule). End with the final ruling."
        )
        start = time.perf_counter()
        usage, result, cost = await _run_claude_json(prompt, ROOT_DIR, TURN_TIMEOUT_S)
        run.turns.append(Turn(
            agent="single", turn=i, duration_s=time.perf_counter() - start,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cost_usd=cost,
        ))
        answer = result.strip()
    run.final_answer = answer
    run.converged = bool(answer)
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

    # Extract the lead's final ruling as the mode's "final answer".
    session = await pool.session_get(orch.session_id)
    final = ""
    for ev in reversed(session.get("activityLog", [])):
        if ev.get("agentId") == "lead" and ev.get("type") == "finished":
            final = (ev.get("payload") or {}).get("output", "")
            break
    if not final:
        for ev in reversed(session.get("activityLog", [])):
            if ev.get("type") == "finished":
                final = (ev.get("payload") or {}).get("output", "")
                break

    return Run(mode="3-agent", converged=bool(status["allSatisfied"]),
               turns=turns, final_answer=final)


async def judge_answer(question: str, answer: str) -> dict:
    prompt = (
        "You are an independent expert judge. Score the following answer to this "
        "question on five criteria, each 1-5 (5 = best):\n\n"
        f"QUESTION:\n{question}\n\nANSWER:\n{answer}\n\n"
        "Criteria:\n"
        "1. correctness   — the ruling is technically sound and aligned with domain consensus\n"
        "2. completeness  — both sides are fairly steelmanned\n"
        "3. specificity   — concrete tradeoffs/examples, not vague\n"
        "4. consistency   — no internal contradictions\n"
        "5. actionability — a reader could act on it directly\n\n"
        "Return ONLY a JSON object, no markdown fences, shaped exactly as:\n"
        '{"criteria":{"correctness":int,"completeness":int,"specificity":int,'
        '"consistency":int,"actionability":int},"total":int,"notes":"one sentence"}'
    )
    usage, result, cost = await _run_claude_json(prompt, ROOT_DIR, JUDGE_TIMEOUT_S)
    text = (result or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group(0)) if m else {"criteria": {}, "notes": "parse failed"}
    criteria = data.get("criteria", {})
    if criteria:
        data["total"] = sum(int(v) for v in criteria.values())
    data["_judge_cost_usd"] = cost
    data["_judge_input_tokens"] = usage.get("input_tokens", 0)
    data["_judge_output_tokens"] = usage.get("output_tokens", 0)
    return data


def _table(runs: list[Run], judge_total_cost: float) -> str:
    lines = [
        "=" * 104,
        f"Efficiency + quality comparison — {QUESTION}",
        "=" * 104,
        f"{'MODE':<22}{'TURNS':>6}{'WALL(s)':>9}{'COST($)':>9}{'SCORE/25':>10}{'$/PT':>8}",
        "-" * 104,
    ]
    for r in runs:
        score = r.judge.get("total", 0)
        per_pt = (r.cost_usd / score) if score else 0.0
        lines.append(f"{r.mode:<22}{r.n_turns:>6}{r.wall_s:>9.1f}{r.cost_usd:>9.4f}"
                     f"{score:>10}{per_pt:>8.3f}")
    lines.append("-" * 104)
    mono = runs[0]
    it = runs[1]
    multi = runs[2]
    lines.append(f"quality_delta (multi vs monolithic) = "
                 f"{multi.judge.get('total',0) - mono.judge.get('total',0):+d} points")
    lines.append(f"quality_delta (multi vs iterative)  = "
                 f"{multi.judge.get('total',0) - it.judge.get('total',0):+d} points")
    lines.append(f"cost overhead: multi x{multi.cost_usd/mono.cost_usd:.2f} (vs mono), "
                 f"x{multi.cost_usd/it.cost_usd:.2f} (vs iterative)")
    lines.append(f"wall overhead: multi x{multi.wall_s/mono.wall_s:.2f} (vs mono), "
                 f"x{multi.wall_s/it.wall_s:.2f} (vs iterative)")
    lines.append(f"judge measurement overhead: ${judge_total_cost:.4f} "
                 f"(excluded from mode costs)")
    return "\n".join(lines)


async def main() -> None:
    print(f"[compare] model: {os.environ.get('ANTHROPIC_MODEL', '(inherit)')}")

    pool = PoolClient(POOL_URL)
    print("[compare] running 3-agent pool ...")
    multi = await run_multi(pool)
    await pool.aclose()
    rounds = max(1, multi.n_turns)
    print(f"[compare] 3-agent converged in {rounds} turns; running single-iterative({rounds}) ...")

    it = await run_single_iterative(rounds)
    print("[compare] running single-monolithic ...")
    mono = await run_single_monolithic()

    runs = [mono, it, multi]
    print("[compare] judging final answers (blind, independent) ...")
    judge_total_cost = 0.0
    for r in runs:
        r.judge = await judge_answer(QUESTION, r.final_answer)
        judge_total_cost += r.judge.get("_judge_cost_usd", 0.0)
        print(f"[compare]   {r.mode:<22} score={r.judge.get('total', 0)}/25")

    table = _table(runs, judge_total_cost)
    print("\n" + table)

    payload = {
        "question": QUESTION,
        "model": os.environ.get("ANTHROPIC_MODEL", "(inherit)"),
        "runs": [
            {
                "mode": r.mode,
                "converged": r.converged,
                "turns": [t.__dict__ for t in r.turns],
                "totals": {"wall_s": r.wall_s, "input_tokens": r.input_tokens,
                           "output_tokens": r.output_tokens,
                           "cache_read_tokens": r.cache_read_tokens,
                           "cost_usd": r.cost_usd},
                "final_answer": r.final_answer,
                "judge": r.judge,
            }
            for r in runs
        ],
    }
    out = Path(RESULTS_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[compare] results written to {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
