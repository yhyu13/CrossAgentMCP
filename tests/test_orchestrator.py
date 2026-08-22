"""Orchestrator convergence + budget tests with fake (deterministic) agents."""
import asyncio

import httpx
import pytest
import pytest_asyncio

from crossagent.orchestrator import Orchestrator
from crossagent.pool import PoolStore, make_pool_app
from crossagent.pool_client import PoolClient


@pytest_asyncio.fixture
async def pool():
    app = make_pool_app(PoolStore())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://pool") as http:
        yield PoolClient("http://pool", http=http)


def _config(agents, max_turns=6):
    return {"goal": "g", "poolUrl": "http://pool", "maxTurns": max_turns,
            "agents": agents}


async def test_converges_when_all_satisfied(pool):
    state = {"sid": None}

    async def runner(agent, prompt):
        await pool.declare_satisfaction(state["sid"], agent["id"], True, "done")
        return f"{agent['id']} done"

    orch = Orchestrator(_config([{"id": "a"}, {"id": "b"}]), pool, agent_runner=runner)
    state["sid"] = await orch.create_session()
    status = await orch.run()
    assert status["allSatisfied"] is True
    assert status["satisfaction"] == {"a": True, "b": True}


async def test_budget_termination_when_never_satisfied(pool):
    async def runner(agent, prompt):
        return "still working"

    orch = Orchestrator(_config([{"id": "a"}, {"id": "b"}], max_turns=4),
                        pool, agent_runner=runner)
    await orch.create_session()
    status = await orch.run()
    assert status["allSatisfied"] is False


async def test_no_progress_guard_fails_chatty_stall(pool):
    # An agent that declares "blocked" every turn emits only bookkeeping activity,
    # so progressCount never rises and the guard must mark the session failed.
    state = {"sid": None}

    async def runner(agent, prompt):
        await pool.declare_satisfaction(state["sid"], agent["id"], False, "blocked")
        return f"{agent['id']} blocked"

    orch = Orchestrator(_config([{"id": "a"}, {"id": "b"}]), pool, agent_runner=runner)
    state["sid"] = await orch.create_session()
    status = await orch.run()
    assert status["state"] == "failed"


async def test_substantive_progress_resets_guard(pool):
    # Posting a substantive "artifact" every turn keeps progressCount rising, so
    # the no-progress guard never trips and the session runs to its turn budget.
    state = {"sid": None}

    async def runner(agent, prompt):
        await pool.post_activity(state["sid"], agent["id"], "artifact", {"note": "work"})
        return f"{agent['id']} worked"

    orch = Orchestrator(_config([{"id": "a"}, {"id": "b"}], max_turns=8),
                        pool, agent_runner=runner)
    state["sid"] = await orch.create_session()
    status = await orch.run()
    assert status["state"] != "failed"


async def test_parallel_schedule_runs_agents_concurrently_and_converges(pool):
    # With schedule="parallel", every agent in a round runs on the same snapshot at
    # once (max_active == len(agents)), and the session still converges.
    state = {"sid": None, "active": 0, "max_active": 0}

    async def runner(agent, prompt):
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.01)
        await pool.declare_satisfaction(state["sid"], agent["id"], True, "done")
        state["active"] -= 1
        return f"{agent['id']} done"

    config = _config([{"id": "a"}, {"id": "b"}, {"id": "c"}])
    config["schedule"] = "parallel"
    orch = Orchestrator(config, pool, agent_runner=runner)
    state["sid"] = await orch.create_session()
    status = await orch.run()
    assert status["allSatisfied"] is True
    assert state["max_active"] == 3


async def test_parallel_schedule_persists_successes_when_an_agent_fails(pool):
    # A mid-round failure must not discard the whole round: sibling agents that
    # completed still get their ``finished`` events persisted, the session is
    # marked failed, and the failure propagates.
    state = {"sid": None}

    async def runner(agent, prompt):
        if agent["id"] == "b":
            raise RuntimeError("boom")
        await asyncio.sleep(0.01)
        return f"{agent['id']} done"

    config = _config([{"id": "a"}, {"id": "b"}, {"id": "c"}])
    config["schedule"] = "parallel"
    orch = Orchestrator(config, pool, agent_runner=runner)
    state["sid"] = await orch.create_session()
    with pytest.raises(RuntimeError, match="boom"):
        await orch.run()
    # Sibling successes are persisted to the pool even though the round failed.
    # (The round cursor resets orch.last_seen, so assert on the pool's own log.)
    events = await pool.activity_since(state["sid"], 0)
    finished = {e["agentId"] for e in events if e["type"] == "finished"}
    assert finished == {"a", "c"}
    assert (await pool.session_status(state["sid"]))["state"] == "failed"


async def test_parallel_default_cursor_next_round_sees_sibling_artifacts(pool):
    # Default parallelCursor="round" restores the pre-round cursor so the
    # next round's prompt contains sibling artifacts posted during gather.
    state = {"sid": None, "calls": {}}
    marker = "SIBLING_ARTIFACT_MARKER"

    async def runner(agent, prompt):
        k = state["calls"][agent["id"]] = state["calls"].get(agent["id"], 0) + 1
        if k >= 2:
            assert marker in prompt, f"{agent['id']} round-2 prompt missed sibling artifacts"
            await pool.declare_satisfaction(state["sid"], agent["id"], True, "ok")
        else:
            await pool.post_activity(state["sid"], agent["id"], "artifact",
                                     {"note": marker})
        return f"{agent['id']} r{k}"

    config = _config([{"id": "a"}, {"id": "b"}, {"id": "c"}], max_turns=9)
    config["schedule"] = "parallel"
    orch = Orchestrator(config, pool, agent_runner=runner)
    assert orch.parallel_cursor == "round"
    state["sid"] = await orch.create_session()
    status = await orch.run()
    assert status["allSatisfied"] is True
    assert all(state["calls"][i] >= 2 for i in ("a", "b", "c"))


async def test_parallel_finish_cursor_drops_sibling_artifacts(pool):
    # Opt-out parallelCursor="finish" is the old bug: last_seen jumps to each
    # agent's own finished seq, so round-2 never sees sibling artifacts.
    state = {"sid": None, "calls": {}, "missed": []}
    marker = "SIBLING_ARTIFACT_MARKER"

    async def runner(agent, prompt):
        k = state["calls"][agent["id"]] = state["calls"].get(agent["id"], 0) + 1
        if k >= 2:
            if marker not in prompt:
                state["missed"].append(agent["id"])
            await pool.declare_satisfaction(state["sid"], agent["id"], True, "ok")
        else:
            await pool.post_activity(state["sid"], agent["id"], "artifact",
                                     {"note": marker})
        return f"{agent['id']} r{k}"

    config = _config([{"id": "a"}, {"id": "b"}, {"id": "c"}], max_turns=9)
    config["schedule"] = "parallel"
    config["parallelCursor"] = "finish"
    orch = Orchestrator(config, pool, agent_runner=runner)
    state["sid"] = await orch.create_session()
    status = await orch.run()
    assert status["allSatisfied"] is True
    assert state["missed"], "finish cursor should drop sibling artifacts"


async def test_max_critiques_pool_failure_stops_orchestrator(pool):
    # A critique storm trips the pool's maxCritiques cap; the orchestrator must
    # detect the pool-initiated ``failed`` state and return instead of burning the
    # whole turn budget.
    state = {"sid": None, "turns": 0}

    async def runner(agent, prompt):
        state["turns"] += 1
        await pool.critique(state["sid"], "a", "b", f"defect {state['turns']}")
        return f"{agent['id']} critiqued"

    config = _config([{"id": "a"}, {"id": "b"}], max_turns=50)
    config["maxCritiques"] = 3
    orch = Orchestrator(config, pool, agent_runner=runner)
    state["sid"] = await orch.create_session()
    status = await orch.run()
    assert status["state"] == "failed"
    assert state["turns"] < 50  # stopped by the cap, not the turn budget
