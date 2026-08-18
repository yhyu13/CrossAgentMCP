"""Headless orchestrator — the only component that advances time.

Drives a multi-agent session to convergence with no human intervention. It
registers the agents into the pool, creates the session, then loops:

1. read ``session_status``; stop when **every member is satisfied and no open
   critique threads remain** (or a turn budget / no-progress guard trips);
2. pick the next agent (round-robin);
3. compose a turn prompt from that agent's *unseen* activity/critique delta and
   the shared goal;
4. run the agent headlessly (``claude -p`` by default) in its own directory;
5. record the turn output as the agent's activity; advance its seen-seq.

The agent runner is injectable so tests can substitute deterministic stubs and
prove convergence without real Claude.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from crossagent.pool_client import PoolClient

AgentRunner = Callable[[dict[str, Any], str], Awaitable[str]]


def claude_argv() -> list[str]:
    """Resolve the ``claude`` launcher on Windows (npm ships a ``.cmd`` shim that
    ``create_subprocess_exec`` cannot spawn without a shell)."""
    exe = shutil.which("claude") or "claude"
    if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
        native = os.path.join(
            os.path.dirname(exe), "node_modules",
            "@anthropic-ai", "claude-code", "bin", "claude.exe")
        if os.path.exists(native):
            return [native]
        return ["cmd.exe", "/d", "/s", "/c", exe]
    return [exe]


DEFAULT_TURN_TIMEOUT_S = 240.0


async def _claude_runner(agent: dict[str, Any], prompt: str) -> str:
    """Run one headless Claude Code turn in the agent's own directory."""
    env = dict(os.environ)
    if agent.get("token"):
        env["CROSSAGENT_POOL_TOKEN"] = agent["token"]
    proc = await asyncio.create_subprocess_exec(
        *claude_argv(), "-p",
        "--permission-mode", "bypassPermissions",
        "--output-format", "text",
        prompt,
        cwd=agent["dir"],
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timeout = float(agent.get("timeoutS", DEFAULT_TURN_TIMEOUT_S))
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        await kill_process_tree(proc)
        raise RuntimeError(f"{agent['id']} timed out after {timeout:g}s")
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {err.decode()}")
    return out.decode()


async def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Terminate the subprocess and its whole tree.

    ``claude`` may spawn MCP child processes, and on Windows the ``.cmd`` shim
    wraps the real ``claude.exe`` in a ``cmd.exe`` parent — ``proc.kill()`` alone
    would orphan those children.
    """
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await killer.communicate()
        except Exception:  # noqa: BLE001 - best effort; the timeout still propagates
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


class Orchestrator:
    def __init__(self, config: dict[str, Any], pool: PoolClient,
                 agent_runner: AgentRunner | None = None) -> None:
        self.config = config
        self.goal: str = config["goal"]
        self.agents: list[dict[str, Any]] = config["agents"]
        self.max_turns: int = config.get("maxTurns", 12)
        self.no_progress_turns: int = config.get("noProgressTurns",
                                                 max(4, 2 * len(self.agents)))
        self.pool = pool
        self.runner = agent_runner or _claude_runner
        self.session_id: str | None = None
        self.last_seen: dict[str, int] = {a["id"]: 0 for a in self.agents}

    # -- lifecycle --
    async def register_all(self) -> None:
        for a in self.agents:
            await self.pool.register(a["id"], url=a.get("url"))

    async def create_session(self) -> str:
        members = [a["id"] for a in self.agents]
        s = await self.pool.session_create(self.goal, members=members)
        self.session_id = s["id"]
        return self.session_id

    # -- turn composition --
    def _prompt(self, agent: dict[str, Any], status: dict[str, Any],
                delta: list[dict[str, Any]]) -> str:
        return "\n".join([
            f"You are agent \"{agent['id']}\" (role: {agent.get('role', 'member')}) "
            "in a shared multi-agent session.",
            "",
            f"Session ID: {self.session_id}",
            f"Shared goal: {self.goal}",
            "",
            f"Session status: {json.dumps(status, indent=2)}",
            "",
            f"New activity since your last turn: {json.dumps(delta, indent=2)}",
            "",
            "Follow your CLAUDE.md turn contract. Work autonomously using your MCP "
            "tools (activity_since, critique_post, activity_post, "
            "declare_satisfaction, session_status) and peer A2A tools as needed. "
            "Critique peers whose work falls short, respond to critiques aimed at you, "
            "and declare whether you are satisfied. Always end your turn by calling "
            "declare_satisfaction with the Session ID above so the session can converge. "
            "Do not wait for a human.",
        ])

    # -- main loop --
    async def run(self) -> dict[str, Any]:
        if not self.session_id:
            await self.create_session()
        assert self.session_id is not None

        turns = 0
        no_progress = 0
        last_sig: tuple[Any, ...] = ()
        while turns < self.max_turns:
            status = await self.pool.session_status(self.session_id)
            if status["allSatisfied"]:
                print(f"[orchestrator] converged after {turns} turns: "
                      f"{json.dumps(status['satisfaction'])}")
                return status

            agent = self.agents[turns % len(self.agents)]
            delta = await self.pool.activity_since(self.session_id,
                                                   self.last_seen[agent["id"]])
            prompt = self._prompt(agent, status, delta)

            print(f"[orchestrator] turn {turns}: {agent['id']} "
                  f"(+{len(delta)} new events)")
            output = await self.runner(agent, prompt)
            output = (output or "").strip()

            ev = await self.pool.post_activity(self.session_id, agent["id"], "finished",
                                               payload={"turn": turns, "output": output[:4000]})
            self.last_seen[agent["id"]] = ev["seq"]
            turns += 1

            # No-progress guard: if satisfaction, the open-critique set, and the
            # count of *substantive* progress events are unchanged for a stretch of
            # turns, the session is stalled — fail it rather than paying for more
            # turns that never converge. Substantive events are artifacts/critiques/
            # self-improvements; bookkeeping (joined/started/finished/satisfied/
            # blocked) is excluded so a chatty-but-static agent is still caught.
            status = await self.pool.session_status(self.session_id)
            sig = (tuple(sorted(status["satisfaction"].items())),
                   tuple(sorted(status["openCritiques"])),
                   status["progressCount"])
            if sig == last_sig:
                no_progress += 1
            else:
                no_progress = 0
                last_sig = sig
            if no_progress >= self.no_progress_turns:
                await self.pool.mark_failed(self.session_id,
                                            "no progress across consecutive turns")
                print(f"[orchestrator] no progress for {no_progress} turns; "
                      f"session marked failed")
                return await self.pool.session_status(self.session_id)

        status = await self.pool.session_status(self.session_id)
        if status["allSatisfied"]:
            print(f"[orchestrator] converged after {turns} turns: "
                  f"{json.dumps(status['satisfaction'])}")
        else:
            print(f"[orchestrator] turn budget exhausted ({self.max_turns} turns); "
                  f"satisfaction={json.dumps(status['satisfaction'])}")
        return status


def load_goal(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m crossagent.orchestrator GOAL_JSON_PATH")
    goal = load_goal(sys.argv[1])
    pool = PoolClient(goal["poolUrl"], token=goal.get("orchestratorToken"))
    orch = Orchestrator(goal, pool)
    try:
        await orch.register_all()
        await orch.run()
    finally:
        await pool.aclose()


if __name__ == "__main__":
    asyncio.run(main())
