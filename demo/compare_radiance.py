"""Head-to-head mono-agent vs 3-agent A2A comparison on the radiance doc tree.

Same task (review ``D:\\GitRepo-My\\radiance-cascades-demo\\3d\\doc``), same model,
same machine. Attaches to the **already-running** stack started by
``scripts/start-servers.ps1`` (open pool :9100 + writer :9101, critic :9102,
lead :9103), mirroring ``review_radiance.py`` / ``compare_efficiency.py``. Runs:

  1. mono-agent   — ONE ``claude -p`` turn with a fused prompt (all roles collapsed:
                    draft + self-critique + integrate) -> writes MONO_REVIEW.md.
  2. 3-agent pool — the Orchestrator (writer/critic/lead) round-robin -> A2A_REVIEW.md.

Both capture identical per-turn metrics (wall time, input/output/cache tokens,
cost) via ``claude -p --output-format json``, then emit a side-by-side table and
the overhead ratios. Results also written to
``demo/output/radiance_comparison.json``.

Run:  uv run python demo/compare_radiance.py [--mono-only | --multi-only]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crossagent.orchestrator import Orchestrator, claude_argv, kill_process_tree
from crossagent.pool_client import PoolClient

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - not a TTY / already reconfigured
    pass

ROOT_DIR = r"D:\GitRepo-AI\CrossAgentMCP"
TARGET_DIR = r"D:\GitRepo-My\radiance-cascades-demo\3d\doc"
MONO_OUTPUT = r"D:\GitRepo-My\radiance-cascades-demo\3d\doc\MONO_REVIEW.md"
MULTI_OUTPUT = r"D:\GitRepo-My\radiance-cascades-demo\3d\doc\A2A_REVIEW.md"
RESULTS_PATH = r"D:\GitRepo-AI\CrossAgentMCP\demo\output\radiance_comparison.json"

POOL_URL = "http://127.0.0.1:9100"
MONO_TIMEOUT_S = 1200
TURN_TIMEOUT_S = 900

# Shared review scope (identical for both modes so the comparison is apples-to-apples).
SCOPE = (
    "The tree holds ~589 markdown files under numbered subdirectories (1..7, then "
    "8_shadertoy, 9_shadertoy2, 10_refactor, 11_generalization, 12_cornell_rc_audit) "
    "plus journey.md (the chronological build narrative) and 13_renderdoc_auto_rdoc.md. "
    "It documents a C++17/OpenGL radiance-cascades global-illumination demo, organized "
    "as plan/impl/critic/reply pairs.\n\n"
    "SCOPE (read the files directly; do not rely on summaries):\n"
    "- Read journey.md in full (it is the spine of the tree).\n"
    "- Read 13_renderdoc_auto_rdoc.md.\n"
    "- For each numbered subdirectory: list its contents and read its index/README "
    "plus a representative sample of plan/impl/critic/reply documents.\n"
    "- Do NOT try to read all ~589 files exhaustively; aim for a representative, "
    "well-grounded sample with concrete file references.\n\n"
    "The review document MUST contain these sections, in order:\n"
    "1. Overview - what the doc tree covers and how it is organized.\n"
    "2. Structure & coverage - a map of the numbered subdirectories and their themes; "
    "note gaps, duplication, or inconsistencies.\n"
    "3. Strengths.\n"
    "4. Findings by severity (Critical / High / Medium / Low). Every finding must cite "
    "a concrete file path (and line reference where possible), state the problem, and "
    "give a suggested fix.\n"
    "5. Recommendations."
)

GOAL_MULTI = (
    f"Perform a review of the 3D Radiance Cascades documentation tree at "
    f"D:/GitRepo-My/radiance-cascades-demo/3d/doc and co-author a single review "
    f"document at D:/GitRepo-My/radiance-cascades-demo/3d/doc/A2A_REVIEW.md.\n\n"
    f"{SCOPE}\n\n"
    "DIVISION OF LABOR:\n"
    "- writer: draft all sections, reading files directly so every claim is grounded "
    "with concrete file references.\n"
    "- critic: verify the writer's claims against the actual files; post critique_post "
    "at writer (or lead) with concrete corrections (wrong refs, missed issues, "
    "mis-stated severity) and add findings the writer missed.\n"
    "- lead: integrate writer + critic into one consistent final document, resolve "
    "disagreements, and give the final sign-off.\n\n"
    "CONVERGENCE RULE: declare_satisfaction(satisfied=true) ONLY when the document is "
    "complete, factually accurate (every finding cites a real file), and all three "
    "roles agree there are no remaining defects. Otherwise declare satisfied=false and "
    "keep working.\n\n"
    "Read the files yourself; do not rely on summaries. Work autonomously; do not wait "
    "for a human."
)

PROMPT_MONO = (
    "You are a senior graphics-engineer documentation reviewer (single agent).\n\n"
    f"Review the 3D Radiance Cascades documentation tree at "
    f"D:/GitRepo-My/radiance-cascades-demo/3d/doc and write a single review document "
    f"to D:/GitRepo-My/radiance-cascades-demo/3d/doc/MONO_REVIEW.md.\n\n"
    f"{SCOPE}\n\n"
    "Do the following in one pass:\n"
    "1. Read the files directly (do not rely on summaries).\n"
    "2. Draft all five sections.\n"
    "3. Self-critique: re-check every finding against the actual files; fix any wrong "
    "references, missed issues, or mis-stated severity.\n"
    "4. Write the final document to the MONO_REVIEW.md path above.\n"
    "5. Return a 3-5 line summary (findings counts by severity + the headline finding).\n\n"
    "Work autonomously; do not wait for a human."
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
    satisfaction: dict[str, Any] = field(default_factory=dict)
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


async def _run_claude_json(prompt: str, cwd: str, timeout_s: float) -> tuple[dict, str, float]:
    """One `claude -p` turn; returns (usage_dict, result_text, total_cost_usd)."""
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


def _backup_multi_output() -> None:
    src = Path(MULTI_OUTPUT)
    if src.exists():
        dst = src.with_name("A2A_REVIEW.prev.md")
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[compare] backed up previous review -> {dst}")


async def run_mono() -> Run:
    run = Run(mode="mono-agent")
    start = time.perf_counter()
    usage, result, cost = await _run_claude_json(PROMPT_MONO, TARGET_DIR, MONO_TIMEOUT_S)
    run.turns.append(Turn(
        agent="mono", turn=0, duration_s=time.perf_counter() - start,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        cost_usd=cost,
    ))
    run.converged = Path(MONO_OUTPUT).exists()
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
    return Run(mode="3-agent", converged=bool(status["allSatisfied"]),
               satisfaction=status.get("satisfaction", {}), turns=turns)


def _table(mono: Run, multi: Run) -> str:
    def row(name, r):
        return (f"{name:<12}{r.n_turns:>6}{r.wall_s:>10.1f}{r.input_tokens:>10}"
                f"{r.output_tokens:>10}{r.cache_read_tokens:>12}{r.cost_usd:>10.4f}")
    lines = [
        "=" * 92,
        f"Radiance doc-tree review — mono vs 3-agent ({TARGET_DIR})",
        "=" * 92,
        f"{'MODE':<12}{'TURNS':>6}{'WALL(s)':>10}{'IN_TOK':>10}{'OUT_TOK':>10}"
        f"{'CACHE_RD':>12}{'COST($)':>10}",
        "-" * 92,
        row("mono-agent", mono),
        row("3-agent", multi),
        "-" * 92,
    ]
    if mono.n_turns and mono.cost_usd:
        lines.append(f"overhead: turns x{multi.n_turns/mono.n_turns:.1f}, "
                     f"wall x{multi.wall_s/mono.wall_s:.2f}, "
                     f"in_tok x{multi.input_tokens/mono.input_tokens:.2f}, "
                     f"out_tok x{multi.output_tokens/mono.output_tokens:.2f}, "
                     f"cost x{multi.cost_usd/mono.cost_usd:.2f}")
    lines.append(f"converged -> mono={mono.converged}, multi={multi.converged} "
                 f"{json.dumps(multi.satisfaction, ensure_ascii=False)}")
    return "\n".join(lines)


def _totals(r: Run) -> dict[str, Any]:
    return {"wall_s": r.wall_s, "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens, "cache_read_tokens": r.cache_read_tokens,
            "cost_usd": r.cost_usd}


async def main() -> None:
    args = set(sys.argv[1:])
    do_mono = "--multi-only" not in args
    do_multi = "--mono-only" not in args

    print(f"[compare] model: {os.environ.get('ANTHROPIC_MODEL', '(inherit from settings.json)')}")
    print(f"[compare] target: {TARGET_DIR}")

    mono = multi = None
    if do_mono:
        print("[compare] running mono-agent baseline (one fused turn) ...")
        mono = await run_mono()
        print(f"[compare] mono done: {mono.n_turns} turn, {mono.wall_s:.1f}s, "
              f"${mono.cost_usd:.4f}, wrote_file={mono.converged}")

    if do_multi:
        _backup_multi_output()
        pool = PoolClient(POOL_URL)
        try:
            print("[compare] running 3-agent A2A pool (attached to :9100) ...")
            multi = await run_multi(pool)
        finally:
            await pool.aclose()
        print(f"[compare] multi done: {multi.n_turns} turns, {multi.wall_s:.1f}s, "
              f"${multi.cost_usd:.4f}, converged={multi.converged}")

    payload: dict[str, Any] = {
        "target": TARGET_DIR,
        "model": os.environ.get("ANTHROPIC_MODEL", "(inherit)"),
    }
    if mono is not None:
        payload["mono"] = {"turns": [asdict(t) for t in mono.turns],
                           "converged": mono.converged, "totals": _totals(mono)}
    if multi is not None:
        payload["multi"] = {"turns": [asdict(t) for t in multi.turns],
                            "converged": multi.converged,
                            "satisfaction": multi.satisfaction, "totals": _totals(multi)}

    if mono is not None and multi is not None:
        print("\n" + _table(mono, multi))
        payload["overhead"] = {
            "turns_x": multi.n_turns / mono.n_turns,
            "wall_x": multi.wall_s / mono.wall_s,
            "in_tok_x": multi.input_tokens / mono.input_tokens,
            "out_tok_x": multi.output_tokens / mono.output_tokens,
            "cost_x": multi.cost_usd / mono.cost_usd,
        }

    out = Path(RESULTS_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[compare] results written to {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
