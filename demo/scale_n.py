"""Scaling-law experiment: N-agent stub sessions on the root orchestrator.

Zero LLM. Sweeps N × {serial, parallel, parallel-2r}:

  serial       — one pass; each agent satisfies immediately (sees 0..N-1 peers)
  parallel     — one bulk-sync round; all satisfy on an empty snapshot
  parallel-2r  — round 1 draft (no satisfy) → round 2 review+satisfy
                 (this is the coordination round the 1-round parallel never pays)

Records prompt bytes (the context-bloat law) and wall. Reports:
  - closed form p0 ≈ a + b(N−1), pΣ_parallel_r1 ≈ N(a + b(N−1))
  - rolling-window α for prompt_sum (not a single global exponent)
  - measured round-2 prompt bytes (not extrapolated)

Run:  uv run python demo/scale_n.py
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from crossagent.orchestrator import Orchestrator
from crossagent.pool import PoolStore, make_pool_app
from crossagent.pool_client import PoolClient

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

NS = (1, 3, 8, 15, 30)
# parallel-2r     — buggy cursor (last_seen = own finished seq; artifacts dropped)
# parallel-2r-fix — parallelCursor=round (next round sees sibling artifacts)
SCHEDULES = ("serial", "parallel", "parallel-2r", "parallel-2r-fix")
WORK_S = 0.05
PAYLOAD_CHARS = 2000
ROUNDS_BUDGET = 3
# Live radiance N=3 serial: $4.56 over 5 agent-turns. Used only as a *relative*
# scale for "if cost ∝ prompt_sum vs that N=3 stub point" — not a per-turn rate.
LIVE_N3_USD = 4.56
OUT = Path(__file__).resolve().parent / "output" / "scale_n.json"


@dataclass
class Point:
    n: int
    schedule: str
    converged: bool
    agent_turns: int
    rounds: float
    wall_s: float
    max_conc: int
    prompt_first: int
    prompt_last: int
    prompt_mean: int
    prompt_sum: int
    prompt_r1_sum: int = 0
    prompt_r2_sum: int = 0
    prompt_r1_last: int = 0
    prompt_r2_last: int = 0
    prompt_r2_first: int = 0


def _fit_loglog(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    pts = [(math.log(x), math.log(y)) for x, y in zip(xs, ys) if x > 0 and y > 0]
    if len(pts) < 2:
        return None
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    num = sum((p[0] - mx) * (p[1] - my) for p in pts)
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den == 0:
        return None
    b = num / den
    pred = [my + b * (p[0] - mx) for p in pts]
    ss_res = sum((p[1] - q) ** 2 for p, q in zip(pts, pred))
    ss_tot = sum((p[1] - my) ** 2 for p in pts)
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 1.0
    return b, r2


def _fit_linear(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """y = a + b x. Returns (a, b) or None."""
    if len(xs) < 2:
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    a = my - b * mx
    return a, b


async def _run_one(n: int, schedule: str) -> Point:
    store = PoolStore()
    app = make_pool_app(store)
    transport = httpx.ASGITransport(app=app)
    prompts: list[int] = []
    conc = {"active": 0, "max": 0}
    calls: dict[str, int] = {}
    two_round = schedule in ("parallel-2r", "parallel-2r-fix")
    orch_sched = "parallel" if two_round else schedule
    orch_cursor = "round" if schedule == "parallel-2r-fix" else "finish"

    async with httpx.AsyncClient(transport=transport, base_url="http://pool") as http:
        pool = PoolClient("http://pool", http=http)
        agents = [{"id": f"a{i}"} for i in range(n)]
        payload = {"note": ("x" * PAYLOAD_CHARS)}

        async def runner(agent: dict[str, Any], prompt: str) -> str:
            prompts.append(len(prompt.encode("utf-8")))
            conc["active"] += 1
            conc["max"] = max(conc["max"], conc["active"])
            await asyncio.sleep(WORK_S)
            await pool.post_activity(orch.session_id, agent["id"], "artifact", payload)
            k = calls[agent["id"]] = calls.get(agent["id"], 0) + 1
            # 1-pass modes satisfy immediately. 2-round parallel only satisfies
            # on the second call so round 1 cannot close the session.
            if (not two_round) or k >= 2:
                await pool.declare_satisfaction(orch.session_id, agent["id"], True, "ok")
            conc["active"] -= 1
            return f"{agent['id']} ok"

        orch = Orchestrator(
            {"goal": "agree", "agents": agents,
             "maxTurns": max(n * ROUNDS_BUDGET, 2 * n + 1),
             "schedule": orch_sched,
             "parallelCursor": orch_cursor,
             "noProgressTurns": max(4, 4 * n)},
            pool, agent_runner=runner)
        t0 = time.perf_counter()
        status = await orch.run()
        wall = time.perf_counter() - t0

    turns = len(prompts)
    rounds = turns / n if n else 0.0
    r1 = prompts[:n]
    r2 = prompts[n:2 * n]
    return Point(
        n=n, schedule=schedule, converged=bool(status.get("allSatisfied")),
        agent_turns=turns, rounds=rounds, wall_s=wall, max_conc=conc["max"],
        prompt_first=prompts[0] if prompts else 0,
        prompt_last=prompts[-1] if prompts else 0,
        prompt_mean=int(sum(prompts) / len(prompts)) if prompts else 0,
        prompt_sum=sum(prompts),
        prompt_r1_sum=sum(r1),
        prompt_r2_sum=sum(r2),
        prompt_r1_last=r1[-1] if r1 else 0,
        prompt_r2_last=r2[-1] if r2 else 0,
        prompt_r2_first=r2[0] if r2 else 0,
    )


def _table(points: list[Point]) -> str:
    hdr = (f"{'N':>4} {'sched':<16} {'conv':>4} {'turns':>6} {'rnd':>5} "
           f"{'wall_s':>8} {'conc':>5} {'p0':>7} {'pN':>7} {'pΣ':>10} "
           f"{'r1Σ':>10} {'r2Σ':>10} {'r2_p0':>7} {'r2_pN':>7}")
    lines = ["=" * len(hdr),
             "N-agent stub scaling  (WORK_S="
             f"{WORK_S}s, PAYLOAD={PAYLOAD_CHARS} chars, 0 LLM)",
             "=" * len(hdr), hdr, "-" * len(hdr)]
    for p in points:
        lines.append(
            f"{p.n:>4} {p.schedule:<16} {'yes' if p.converged else 'no':>4} "
            f"{p.agent_turns:>6} {p.rounds:>5.2f} {p.wall_s:>8.3f} {p.max_conc:>5} "
            f"{p.prompt_first:>7} {p.prompt_last:>7} {p.prompt_sum:>10} "
            f"{p.prompt_r1_sum:>10} {p.prompt_r2_sum:>10} "
            f"{p.prompt_r2_first:>7} {p.prompt_r2_last:>7}")
    lines.append("-" * len(hdr))
    return "\n".join(lines)


def _rolling_alpha(subset: list[Point], attr: str) -> list[str]:
    lines = []
    for i in range(len(subset) - 1):
        a, b = subset[i], subset[i + 1]
        ya, yb = float(getattr(a, attr)), float(getattr(b, attr))
        if a.n <= 0 or ya <= 0 or yb <= 0:
            continue
        alpha = math.log(yb / ya) / math.log(b.n / a.n)
        lines.append(f"    N={a.n}→{b.n}  α={alpha:+.2f}")
    return lines


def _analysis(points: list[Point]) -> list[str]:
    lines: list[str] = ["", "--- closed form + rolling α (not a single global exponent) ---"]

    par = [p for p in points if p.schedule == "parallel" and p.n >= 3]
    if len(par) >= 2:
        # p0(N) = a + b(N-1)  (roster term)
        fit = _fit_linear([float(p.n - 1) for p in par],
                          [float(p.prompt_first) for p in par])
        if fit:
            a, b = fit
            lines.append(f"parallel p0 ≈ {a:.0f} + {b:.1f}(N−1)   "
                         f"→ pΣ_r1 ≈ N·({a:.0f} + {b:.1f}(N−1)) = {a:.0f}N + {b:.1f}N(N−1)")
            lines.append("  (roster is O(N) per prompt × N agents = O(N²); "
                         "local α rises toward 2)")
            lines.append("  rolling α(parallel prompt_sum):")
            lines.extend(_rolling_alpha(par, "prompt_sum"))

    ser = [p for p in points if p.schedule == "serial" and p.n >= 3]
    if len(ser) >= 2:
        # event bytes: (pΣ − N·p0) / (N(N−1)/2)
        e_vals = []
        for p in ser:
            pairs = p.n * (p.n - 1) / 2
            if pairs <= 0:
                continue
            e_vals.append((p.prompt_sum - p.n * p.prompt_first) / pairs)
        e_hat = sum(e_vals) / len(e_vals) if e_vals else 0.0
        lines.append(f"serial event-bytes ê ≈ {e_hat:.0f} B/finished-peer  "
                     f"(pΣ ≈ N·p0 + ê·N(N−1)/2)")
        lines.append("  rolling α(serial prompt_sum):")
        lines.extend(_rolling_alpha(ser, "prompt_sum"))

    for label, key in (("parallel-2r (vacuous: artifacts dropped)", "parallel-2r"),
                       ("parallel-2r-fix (round cursor: artifacts re-fed)", "parallel-2r-fix")):
        two = [p for p in points if p.schedule == key and p.n >= 3]
        if not two:
            continue
        lines.append(f"{label}:")
        for p in two:
            ratio = (p.prompt_r2_sum / p.prompt_r1_sum) if p.prompt_r1_sum else 0.0
            ser_p = next((s for s in ser if s.n == p.n), None)
            vs_ser = (p.prompt_sum / ser_p.prompt_sum) if ser_p and ser_p.prompt_sum else 0.0
            lines.append(
                f"  N={p.n:>2}  r1Σ={p.prompt_r1_sum:>8}  r2Σ={p.prompt_r2_sum:>8}  "
                f"r2/r1={ratio:.2f}  (r1+r2)/serial={vs_ser:.2f}  "
                f"r2_p0={p.prompt_r2_first} r2_pN={p.prompt_r2_last}")
        lines.append(f"  rolling α({key} prompt_sum = r1+r2):")
        lines.extend(_rolling_alpha(two, "prompt_sum"))
        lines.append(f"  rolling α({key} r2Σ only):")
        lines.extend(_rolling_alpha(two, "prompt_r2_sum"))

    # relative "if cost ∝ prompt_sum" vs N=3 serial stub — NOT a $0.91/turn rate
    n3 = next((p for p in ser if p.n == 3), None)
    if n3 and n3.prompt_sum:
        lines.append("")
        lines.append(f"if cost ∝ prompt_sum, scaled to live N=3 serial ${LIVE_N3_USD:.2f} "
                     f"(stub pΣ_N3={n3.prompt_sum} B). This is a *relative* scale, "
                     "not a per-turn dollar rate:")
        lines.append(f"  {'sched':<16} {'N':>4} {'pΣ':>10} {'×N3':>8} {'$rel':>8}")
        for p in points:
            if p.n < 3:
                continue
            x = p.prompt_sum / n3.prompt_sum
            note = ""
            if p.schedule == "parallel-2r":
                note = "  (vacuous r2)"
            elif p.schedule == "parallel-2r-fix":
                note = "  (artifacts in r2)"
            lines.append(f"  {p.schedule:<16} {p.n:>4} {p.prompt_sum:>10} "
                         f"{x:>8.1f} {LIVE_N3_USD * x:>8.1f}{note}")

    lines.append("")
    lines.append("wall (measured): parallel/parallel-2r wall is max(turn)+overhead, "
                 "not Σ; serial wall ~ N.")
    return lines


async def main() -> None:
    points: list[Point] = []
    for n in NS:
        for sched in SCHEDULES:
            print(f"[scale] N={n} {sched} ...", flush=True)
            p = await _run_one(n, sched)
            points.append(p)
            extra = ""
            if sched in ("parallel-2r", "parallel-2r-fix"):
                extra = f" r1Σ={p.prompt_r1_sum} r2Σ={p.prompt_r2_sum}"
            print(f"[scale]   conv={p.converged} turns={p.agent_turns} "
                  f"wall={p.wall_s:.3f}s conc={p.max_conc} "
                  f"prompt {p.prompt_first}→{p.prompt_last} B{extra}", flush=True)

    print("\n" + _table(points))
    print("\n".join(_analysis(points)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "work_s": WORK_S, "payload_chars": PAYLOAD_CHARS,
        "live_n3_usd": LIVE_N3_USD,
        "points": [asdict(p) for p in points],
    }, indent=2), encoding="utf-8")
    print(f"\n[scale] wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
