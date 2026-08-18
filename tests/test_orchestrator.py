"""Orchestrator convergence + budget tests with fake (deterministic) agents."""
import httpx
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
