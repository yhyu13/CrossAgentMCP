"""Autonomous A2A review of the radiance-cascades-demo ``3d/doc`` tree.

Unlike ``review_demo.py`` (which boots its own in-process pool + A2A servers), this
script attaches to the **already-running** stack started by
``scripts/start-servers.ps1`` (pool :9100 open/no-auth + writer :9101, critic :9102,
lead :9103). It runs the headless orchestrator with three real ``claude -p`` agents
to co-author a review of ``D:\\GitRepo-My\\radiance-cascades-demo\\3d\\doc`` and, once
the session finishes, dumps the full conversation (activity log + critique threads) to
stdout and to ``demo/output/radiance_review_transcript.md``.

Run:  uv run python demo/review_radiance.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crossagent.orchestrator import Orchestrator
from crossagent.pool_client import PoolClient

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - not a TTY / already reconfigured
    pass

POOL_URL = "http://127.0.0.1:9100"

TARGET_DIR = r"D:\GitRepo-My\radiance-cascades-demo\3d\doc"
OUTPUT_PATH = r"D:\GitRepo-My\radiance-cascades-demo\3d\doc\A2A_REVIEW.md"
TRANSCRIPT_PATH = r"D:\GitRepo-AI\CrossAgentMCP\demo\output\radiance_review_transcript.md"

GOAL = (
    "Perform a review of the 3D Radiance Cascades documentation tree at "
    "D:/GitRepo-My/radiance-cascades-demo/3d/doc and co-author a single review "
    "document at D:/GitRepo-My/radiance-cascades-demo/3d/doc/A2A_REVIEW.md.\n\n"
    "The tree holds ~591 markdown files under numbered subdirectories (1..13) plus "
    "journey.md (the chronological build narrative) and 13_renderdoc_auto_rdoc.md. It "
    "documents a C++17/OpenGL radiance-cascades global-illumination demo, organized as "
    "plan/impl/critic/reply pairs.\n\n"
    "SCOPE (read the files directly; do not rely on summaries):\n"
    "- Read journey.md in full (it is the spine of the tree).\n"
    "- Read 13_renderdoc_auto_rdoc.md.\n"
    "- For each numbered subdirectory 1..13: list its contents and read its index/"
    "README plus a representative sample of plan/impl/critic/reply documents.\n"
    "- Do NOT try to read all 591 files exhaustively; aim for a representative, "
    "well-grounded sample with concrete file references.\n\n"
    "The review document MUST contain these sections, in order:\n"
    "1. Overview - what the doc tree covers and how it is organized.\n"
    "2. Structure & coverage - a map of the numbered subdirectories and their themes; "
    "note gaps, duplication, or inconsistencies.\n"
    "3. Strengths.\n"
    "4. Findings by severity (Critical / High / Medium / Low). Every finding must cite "
    "a concrete file path (and line reference where possible), state the problem, and "
    "give a suggested fix.\n"
    "5. Recommendations.\n\n"
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

AGENTS = [
    {"id": "writer", "role": "writer", "dir": "D:/GitRepo-AI/CrossAgentMCP/agents/writer",
     "url": "http://127.0.0.1:9101", "timeoutS": 600},
    {"id": "critic", "role": "critic", "dir": "D:/GitRepo-AI/CrossAgentMCP/agents/critic",
     "url": "http://127.0.0.1:9102", "timeoutS": 600},
    {"id": "lead", "role": "lead", "dir": "D:/GitRepo-AI/CrossAgentMCP/agents/lead",
     "url": "http://127.0.0.1:9103", "timeoutS": 600},
]


def _render(session: dict, critiques: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# Radiance Cascades doc review — A2A conversation transcript")
    lines.append("")
    lines.append(f"- Session: `{session['id']}`")
    lines.append(f"- State: **{session.get('state')}**")
    lines.append(f"- Members: {', '.join(session.get('members', []))}")
    lines.append(f"- Satisfaction: {json.dumps(session.get('satisfaction', {}), ensure_ascii=False)}")
    lines.append(f"- Activity events: {len(session.get('activityLog', []))}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Activity log (chronological)")
    lines.append("")
    for ev in session.get("activityLog", []):
        agent = ev.get("agentId", "?")
        etype = ev.get("type", "?")
        tgt = ev.get("targetAgentId")
        header = f"### [{ev.get('seq')}] `{agent}` :: `{etype}`"
        if tgt:
            header += f" → `{tgt}`"
        lines.append(header)
        lines.append("")
        payload = ev.get("payload") or {}
        if etype == "finished" and payload.get("output"):
            lines.append("```text")
            lines.append(str(payload["output"]))
            lines.append("```")
        elif etype in ("critique", "self-improved") and payload.get("text"):
            lines.append(f"> {payload['text']}")
        elif etype in ("satisfied", "blocked") and payload.get("summary"):
            lines.append(f"> summary: {payload['summary']}")
        elif payload:
            lines.append("```json")
            lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Critique threads")
    lines.append("")
    if not critiques:
        lines.append("_(none)_")
    for c in critiques:
        state = "open" if c.get("open") else "resolved"
        lines.append(f"### thread `{c['id']}` — {state}")
        lines.append(f"- by `{c.get('authorAgentId')}` → `{c.get('targetAgentId')}`")
        lines.append("")
        for h in c.get("history", []):
            lines.append(f"- **{h.get('role')}**: {h.get('text')}")
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    pool = PoolClient(POOL_URL)
    orch = Orchestrator({"goal": GOAL, "agents": AGENTS, "maxTurns": 9}, pool)
    try:
        await orch.register_all()
        await orch.create_session()
        print(f"[review] session {orch.session_id} created; goal: 3d/doc review")
        status = await orch.run()

        print("\n" + "=" * 72)
        print("[review] final session status:")
        print(json.dumps(status, indent=2, ensure_ascii=False))

        session = await pool.session_get(orch.session_id)
        critiques = await pool.list_critiques(orch.session_id)
        transcript = _render(session, critiques)

        out_dir = Path(TRANSCRIPT_PATH).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        Path(TRANSCRIPT_PATH).write_text(transcript, encoding="utf-8")
        print(f"\n[review] transcript written to {TRANSCRIPT_PATH}")

        try:
            content = Path(OUTPUT_PATH).read_text(encoding="utf-8")
            print(f"[review] review doc: {len(content)} chars at {OUTPUT_PATH}")
        except FileNotFoundError:
            print(f"[review] WARNING: {OUTPUT_PATH} was not created")

        print("\n" + "=" * 72)
        print(transcript)
    finally:
        await pool.aclose()


if __name__ == "__main__":
    asyncio.run(main())
