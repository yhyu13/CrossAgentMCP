"""Head-to-head mono vs 3-agent comparison on the radiance doc tree, using the
``1/`` A2A pool (not the root ``crossagent/`` stack).

Boots its own pool + 3 agent A2A servers on **auto-selected free ports** so it
does not collide with the root stack on :9100-9103. Each 3-agent turn is a real
``claude -p`` process whose ``.mcp.json`` talks to this pool via
``shared.mcp_bridge``. Metrics come from ``--output-format json``.

Run from ``1/``:

    uv run python demo/compare_radiance.py [--mono-only | --multi-only]
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from pool.coordinator import make_coordinator  # noqa: E402
from pool.store import PoolStore, Session  # noqa: E402
from shared.pool_client import PoolClient  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

TARGET_DIR = r"D:\GitRepo-My\radiance-cascades-demo\3d\doc"
MONO_OUTPUT = r"D:\GitRepo-My\radiance-cascades-demo\3d\doc\MONO_REVIEW_1.md"
MULTI_OUTPUT = r"D:\GitRepo-My\radiance-cascades-demo\3d\doc\A2A_REVIEW_1.md"
RESULTS_PATH = str(HERE / "output" / "radiance_comparison.json")

MONO_TIMEOUT_S = 1200
TURN_TIMEOUT_S = 900
MAX_TURNS = 9
SESSION_TIMEOUT_S = 3600.0

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
    f"document at D:/GitRepo-My/radiance-cascades-demo/3d/doc/A2A_REVIEW_1.md.\n\n"
    f"{SCOPE}\n\n"
    "DIVISION OF LABOR:\n"
    "- writer: draft all sections, reading files directly so every claim is grounded "
    "with concrete file references.\n"
    "- critic: verify the writer's claims against the actual files; post "
    "agentpool_critique at writer (or lead) with concrete corrections (wrong refs, "
    "missed issues, mis-stated severity) and add findings the writer missed.\n"
    "- lead: integrate writer + critic into one consistent final document, resolve "
    "disagreements, and give the final sign-off.\n\n"
    "CONVERGENCE RULE: agentpool_declare_satisfaction ONLY when the document is "
    "complete, factually accurate (every finding cites a real file), and all three "
    "roles agree there are no remaining defects. Otherwise keep working.\n\n"
    "Read the files yourself; do not rely on summaries. Work autonomously; do not wait "
    "for a human."
)

PROMPT_MONO = (
    "You are a senior graphics-engineer documentation reviewer (single agent).\n\n"
    f"Review the 3D Radiance Cascades documentation tree at "
    f"D:/GitRepo-My/radiance-cascades-demo/3d/doc and write a single review document "
    f"to D:/GitRepo-My/radiance-cascades-demo/3d/doc/MONO_REVIEW_1.md.\n\n"
    f"{SCOPE}\n\n"
    "Do the following in one pass:\n"
    "1. Read the files directly (do not rely on summaries).\n"
    "2. Draft all five sections.\n"
    "3. Self-critique: re-check every finding against the actual files; fix any wrong "
    "references, missed issues, or mis-stated severity.\n"
    "4. Write the final document to the MONO_REVIEW_1.md path above.\n"
    "5. Return a 3-5 line summary (findings counts by severity + the headline finding).\n\n"
    "Work autonomously; do not wait for a human."
)

ROLES = [
    {"id": "writer", "role": "drafts the review from primary sources"},
    {"id": "critic", "role": "verifies claims and posts concrete critiques"},
    {"id": "lead", "role": "integrates writer+critic and signs off"},
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def claude_argv() -> list[str]:
    exe = shutil.which("claude") or "claude"
    if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
        native = os.path.join(
            os.path.dirname(exe), "node_modules",
            "@anthropic-ai", "claude-code", "bin", "claude.exe")
        if os.path.exists(native):
            return [native]
        return ["cmd.exe", "/d", "/s", "/c", exe]
    return [exe]


async def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    if sys.platform == "win32" and proc.pid:
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await killer.communicate()
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await proc.wait()
    except Exception:  # noqa: BLE001
        pass


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
    session_state: str = ""

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


def _scaffold_agent(agent_id: str, port: int, role: str, pool_url: str) -> Path:
    tpl = ROOT / "agent-template"
    out = ROOT / "agents" / agent_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "server.py").write_text((tpl / "server.py").read_text(encoding="utf-8"),
                                   encoding="utf-8")
    local_url = f"http://127.0.0.1:{port}"

    def render(src: str) -> str:
        return (src
                .replace("{ROOT}", str(ROOT))
                .replace("{NAME}", agent_id)
                .replace("{SELF_ID}", agent_id)
                .replace("{POOL_URL}", pool_url)
                .replace("{LOCAL_URL}", local_url)
                .replace("{AGENT_ID}", agent_id)
                .replace("{AGENT_ROLE}", role))

    (out / "CLAUDE.md").write_text(
        render((tpl / "CLAUDE.md").read_text(encoding="utf-8")), encoding="utf-8")
    (out / ".mcp.json").write_text(
        render((tpl / ".mcp.json").read_text(encoding="utf-8")), encoding="utf-8")
    return out


async def _serve_pool(store: PoolStore, port: int) -> tuple[uvicorn.Server, asyncio.Task]:
    app = make_coordinator(store)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(80):
        if server.started:
            break
        await asyncio.sleep(0.05)
    if not server.started:
        raise RuntimeError(f"pool failed to start on :{port}")
    return server, task


async def _boot_agent_server(agent_id: str, port: int, role: str) -> asyncio.subprocess.Process:
    env = {**os.environ,
           "AGENT_ID": agent_id, "AGENT_NAME": agent_id,
           "AGENT_PORT": str(port), "AGENT_ROLE": role}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "agents" / agent_id / "server.py"),
        cwd=str(ROOT), env=env,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    # wait until the A2A card is reachable
    import httpx
    url = f"http://127.0.0.1:{port}/.well-known/agent-card.json"
    async with httpx.AsyncClient() as c:
        for _ in range(80):
            try:
                r = await c.get(url, timeout=1.0)
                if r.status_code == 200:
                    return proc
            except Exception:  # noqa: BLE001
                pass
            if proc.returncode is not None:
                raise RuntimeError(f"{agent_id} A2A server exited {proc.returncode}")
            await asyncio.sleep(0.1)
    raise RuntimeError(f"{agent_id} A2A server did not come up on :{port}")


def _prompt(agent: dict[str, Any], sid: str, status: dict[str, Any],
            delta: list[dict[str, Any]]) -> str:
    return "\n".join([
        f"You are agent \"{agent['id']}\" (role: {agent['role']}) in a shared "
        "multi-agent session on the 1/ A2A pool.",
        "",
        f"Session ID: {sid}",
        f"Shared goal: {GOAL_MULTI}",
        "",
        f"Session status: {json.dumps(status, indent=2, default=str)}",
        "",
        f"New activity since your last turn: {json.dumps(delta, indent=2, default=str)}",
        "",
        "Follow your CLAUDE.md turn contract. You are already registered and joined; "
        "do not re-create the session. Use your MCP tools (agentpool_session_status, "
        "agentpool_watch, agentpool_post_activity, agentpool_critique, "
        "agentpool_resolve_critique, agentpool_declare_satisfaction) and peer A2A "
        "tools as needed. Critique peers whose work falls short, respond to critiques "
        "aimed at you, write/revise A2A_REVIEW_1.md, and declare satisfaction when "
        "the document is complete and accurate. Do not wait for a human.",
    ])


async def run_mono() -> Run:
    run = Run(mode="mono-agent")
    start = time.perf_counter()
    usage, _result, cost = await _run_claude_json(PROMPT_MONO, TARGET_DIR, MONO_TIMEOUT_S)
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


async def run_multi() -> Run:
    store = PoolStore()
    pool_port = _free_port()
    agent_ports = {r["id"]: _free_port() for r in ROLES}
    pool_url = f"http://127.0.0.1:{pool_port}"

    for r in ROLES:
        _scaffold_agent(r["id"], agent_ports[r["id"]], r["role"], pool_url)
        print(f"[compare] scaffolded {r['id']} on :{agent_ports[r['id']]}")

    pool_server, pool_task = await _serve_pool(store, pool_port)
    print(f"[compare] 1/ pool on {pool_url}")
    agent_procs: list[asyncio.subprocess.Process] = []
    pool = PoolClient(pool_url)
    turns: list[Turn] = []
    try:
        for r in ROLES:
            p = await _boot_agent_server(r["id"], agent_ports[r["id"]], r["role"])
            agent_procs.append(p)
            print(f"[compare] {r['id']} A2A up")

        session = await pool.create_session(GOAL_MULTI)
        sid = session["id"]
        s: Session | None = store.get_session(sid)
        if s is None:
            raise RuntimeError("session vanished after create")
        s.timeoutSec = SESSION_TIMEOUT_S
        s.maxIterations = 50

        for r in ROLES:
            await pool.register(
                r["id"],
                {"name": r["id"], "description": r["role"]},
                f"http://127.0.0.1:{agent_ports[r['id']]}/")
            await pool.join_session(sid, r["id"])
        print(f"[compare] session {sid} members={ [r['id'] for r in ROLES] }")

        last_seen = {r["id"]: 0 for r in ROLES}
        for i in range(MAX_TURNS):
            st = await pool.session_status(sid)
            if st.get("state") == "satisfied":
                print(f"[compare] converged after {i} turns")
                break
            agent = ROLES[i % len(ROLES)]
            delta = await pool.activity_list(sid, last_seen[agent["id"]])
            print(f"[compare] turn {i}: {agent['id']} (+{len(delta)} events, "
                  f"state={st.get('state')})")
            start = time.perf_counter()
            try:
                usage, result, cost = await _run_claude_json(
                    _prompt(agent, sid, st, delta),
                    str(ROOT / "agents" / agent["id"]),
                    TURN_TIMEOUT_S)
            except Exception as e:  # noqa: BLE001
                turns.append(Turn(agent=agent["id"], turn=i))
                raise RuntimeError(f"{agent['id']}: {e}") from e
            turns.append(Turn(
                agent=agent["id"], turn=i,
                duration_s=time.perf_counter() - start,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                cost_usd=cost,
            ))
            # bump last_seen to current activity length so next turn is a delta
            st2 = await pool.session_status(sid)
            last_seen[agent["id"]] = len(st2.get("activity") or [])
            print(f"[compare]   {agent['id']} done {turns[-1].duration_s:.1f}s "
                  f"${turns[-1].cost_usd:.4f} state={st2.get('state')}")
        else:
            st = await pool.session_status(sid)

        st = await pool.session_status(sid)
        return Run(mode="3-agent-1/",
                   converged=st.get("state") == "satisfied",
                   satisfaction=st.get("satisfaction") or {},
                   session_state=st.get("state") or "",
                   turns=turns)
    finally:
        await pool.aclose()
        for p in agent_procs:
            await kill_process_tree(p)
        pool_server.should_exit = True
        await pool_task


def _totals(r: Run) -> dict[str, Any]:
    return {"wall_s": r.wall_s, "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens, "cache_read_tokens": r.cache_read_tokens,
            "cost_usd": r.cost_usd}


def _table(mono: Run, multi: Run) -> str:
    def row(name, r):
        return (f"{name:<14}{r.n_turns:>6}{r.wall_s:>10.1f}{r.input_tokens:>10}"
                f"{r.output_tokens:>10}{r.cache_read_tokens:>12}{r.cost_usd:>10.4f}")
    lines = [
        "=" * 94,
        f"1/ A2A pool — radiance doc-tree review — mono vs 3-agent ({TARGET_DIR})",
        "=" * 94,
        f"{'MODE':<14}{'TURNS':>6}{'WALL(s)':>10}{'IN_TOK':>10}{'OUT_TOK':>10}"
        f"{'CACHE_RD':>12}{'COST($)':>10}",
        "-" * 94,
        row("mono-agent", mono),
        row("3-agent-1/", multi),
        "-" * 94,
    ]
    if mono.n_turns and mono.cost_usd:
        lines.append(f"overhead: turns x{multi.n_turns/mono.n_turns:.1f}, "
                     f"wall x{multi.wall_s/mono.wall_s:.2f}, "
                     f"in_tok x{multi.input_tokens/max(mono.input_tokens,1):.2f}, "
                     f"out_tok x{multi.output_tokens/max(mono.output_tokens,1):.2f}, "
                     f"cost x{multi.cost_usd/mono.cost_usd:.2f}")
    lines.append(f"converged -> mono={mono.converged}, multi={multi.converged} "
                 f"state={multi.session_state} {json.dumps(multi.satisfaction)}")
    return "\n".join(lines)


async def main() -> None:
    args = set(sys.argv[1:])
    do_mono = "--multi-only" not in args
    do_multi = "--mono-only" not in args
    print(f"[compare] 1/ A2A pool vs radiance 3d/doc")
    print(f"[compare] model: {os.environ.get('ANTHROPIC_MODEL', '(inherit from settings.json)')}")

    mono = multi = None
    if do_mono:
        print("[compare] running mono-agent baseline ...")
        mono = await run_mono()
        print(f"[compare] mono done: {mono.n_turns} turn, {mono.wall_s:.1f}s, "
              f"${mono.cost_usd:.4f}, wrote_file={mono.converged}")

    if do_multi:
        print("[compare] running 3-agent 1/ A2A pool ...")
        multi = await run_multi()
        print(f"[compare] multi done: {multi.n_turns} turns, {multi.wall_s:.1f}s, "
              f"${multi.cost_usd:.4f}, converged={multi.converged} "
              f"state={multi.session_state}")

    payload: dict[str, Any] = {
        "impl": "1/",
        "target": TARGET_DIR,
        "model": os.environ.get("ANTHROPIC_MODEL", "(inherit)"),
    }
    if mono is not None:
        payload["mono"] = {"turns": [asdict(t) for t in mono.turns],
                           "converged": mono.converged, "totals": _totals(mono)}
    if multi is not None:
        payload["multi"] = {"turns": [asdict(t) for t in multi.turns],
                            "converged": multi.converged,
                            "session_state": multi.session_state,
                            "satisfaction": multi.satisfaction,
                            "totals": _totals(multi)}
    if mono is not None and multi is not None and mono.cost_usd:
        print("\n" + _table(mono, multi))
        payload["overhead"] = {
            "turns_x": multi.n_turns / max(mono.n_turns, 1),
            "wall_x": multi.wall_s / mono.wall_s,
            "in_tok_x": multi.input_tokens / max(mono.input_tokens, 1),
            "out_tok_x": multi.output_tokens / max(mono.output_tokens, 1),
            "cost_x": multi.cost_usd / mono.cost_usd,
        }
    out = Path(RESULTS_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[compare] results written to {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
