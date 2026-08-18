"""Metrics over a finished session's activity log.

Token figures are *estimates* from message payload text (~4 chars/token), a
proxy for what a real LLM agent would consume writing/reading activity. Timing
comes from each event's `ts` timestamp (UTC ISO).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def estimate_tokens(text: str) -> int:
    """Rough English token estimate (~4 chars/token) for message payloads."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def compute_session_metrics(session: dict[str, Any]) -> dict[str, Any]:
    events = session.get("activity", [])
    start = _ts(session.get("startTs"))

    agents: dict[str, dict[str, Any]] = {}

    def rec(aid: str) -> dict[str, Any]:
        return agents.setdefault(aid, {
            "agentId": aid, "events": 0, "tokens_out": 0,
            "critiques_sent": 0, "critiques_received": 0,
            "self_improvements": 0, "finished": 0,
            "first_ts": None, "last_ts": None,
        })

    total_tokens = 0
    n_critiques = 0
    n_self_improved = 0
    first_finished_ts: datetime | None = None
    end_ts = start
    critique_ts: dict[str, datetime] = {}
    resolve_ts: dict[str, datetime] = {}

    for ev in events:
        aid = ev["agentId"]
        if aid == "pool":
            continue
        r = rec(aid)
        t = _ts(ev["ts"])
        r["events"] += 1
        if r["first_ts"] is None or t < r["first_ts"]:
            r["first_ts"] = t
        if r["last_ts"] is None or t > r["last_ts"]:
            r["last_ts"] = t
        if t > end_ts:
            end_ts = t

        tok = estimate_tokens(ev.get("payload") or "")
        total_tokens += tok
        r["tokens_out"] += tok

        etype = ev["type"]
        if etype == "critique":
            n_critiques += 1
            r["critiques_sent"] += 1
            if ev.get("critiqueId"):
                critique_ts[ev["critiqueId"]] = t
        elif etype == "self-improved":
            n_self_improved += 1
            r["self_improvements"] += 1
            if ev.get("critiqueId"):
                resolve_ts[ev["critiqueId"]] = t
        elif etype == "finished":
            r["finished"] += 1
            if first_finished_ts is None:
                first_finished_ts = t

    for ev in events:
        if ev["type"] == "critique" and ev.get("targetAgentId"):
            target = agents.get(ev["targetAgentId"])
            if target:
                target["critiques_received"] += 1

    terminal_ts: datetime | None = None
    for ev in events:
        if ev["type"] in ("session-completed", "session-failed"):
            terminal_ts = _ts(ev["ts"])
            break

    wall = (end_ts - start).total_seconds()
    time_to_terminal = (terminal_ts - start).total_seconds() if terminal_ts else None
    time_to_first_finished = (
        (first_finished_ts - start).total_seconds() if first_finished_ts else None)

    latencies = [(resolve_ts[c] - critique_ts[c]).total_seconds()
                 for c in critique_ts if c in resolve_ts]
    avg_crit_resolve = sum(latencies) / len(latencies) if latencies else None

    per_agent = []
    for aid in sorted(agents):
        r = agents[aid]
        active = (r["last_ts"] - r["first_ts"]).total_seconds() if r["first_ts"] else 0.0
        per_agent.append({
            "agentId": aid,
            "events": r["events"],
            "tokens_out": r["tokens_out"],
            "critiques_sent": r["critiques_sent"],
            "critiques_received": r["critiques_received"],
            "self_improvements": r["self_improvements"],
            "finished": r["finished"],
            "active_sec": round(active, 3),
        })

    return {
        "state": session.get("state"),
        "members": len(session.get("members", [])),
        "iterations": session.get("iteration"),
        "failedReason": session.get("failedReason"),
        "events": len(events),
        "critiques": n_critiques,
        "self_improvements": n_self_improved,
        "tokens_est": total_tokens,
        "wall_sec": round(wall, 3),
        "time_to_terminal_sec": round(time_to_terminal, 3)
        if time_to_terminal is not None else None,
        "time_to_first_finished_sec": round(time_to_first_finished, 3)
        if time_to_first_finished is not None else None,
        "avg_critique_resolve_sec": round(avg_crit_resolve, 3)
        if avg_crit_resolve is not None else None,
        "per_agent": per_agent,
    }
