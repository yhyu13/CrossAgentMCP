"""Bridge-layer tests: self-identity is bound at build time, so an agent's MCP
bridge cannot spoof another agent's activity, critique, or resolution."""
import httpx
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session

from crossagent.a2a_bridge import build_server
from crossagent.pool import PoolStore, make_pool_app
from crossagent.pool_client import PoolClient


@pytest_asyncio.fixture
async def pool():
    app = make_pool_app(PoolStore())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://pool") as http:
        yield PoolClient("http://pool", http=http)


def _build(agent_id: str, pool: PoolClient):
    return build_server("bridge", agent_id, {}, "http://local",
                        "http://pool", pool=pool)


async def _tool_text(client, name, args):
    r = await client.call_tool(name, args)
    return r.content[0].text


async def test_resolve_critique_identity_binding(pool):
    # agent "a" critiques agent "b"; only b's own bridge may close the thread.
    s = await pool.session_create("goal", members=["a", "b"])
    c = await pool.critique(s["id"], "a", "b", "fix this section")
    cid = c["id"]

    async with create_connected_server_and_client_session(_build("a", pool)) as client_a:
        text = await _tool_text(client_a, "resolve_critique",
                                {"sessionId": s["id"], "critiqueId": cid, "text": "done"})
        assert "not authorized" in text  # a is not the target

    async with create_connected_server_and_client_session(_build("b", pool)) as client_b:
        text = await _tool_text(client_b, "resolve_critique",
                                {"sessionId": s["id"], "critiqueId": cid, "text": "done"})
        assert "error" not in text  # b (the target) may resolve

    assert (await pool.session_status(s["id"]))["openCritiques"] == []


async def test_activity_and_satisfaction_are_self_bound(pool):
    # the bridge never accepts an agent id from the caller — it always uses its own.
    async with create_connected_server_and_client_session(_build("a", pool)) as client:
        s = await pool.session_create("goal", members=["a"])
        await client.call_tool("activity_post",
                               {"sessionId": s["id"], "type": "artifact",
                                "payload": {"from": "whoever"}})
        await client.call_tool("declare_satisfaction",
                               {"sessionId": s["id"], "satisfied": True})

    status = await pool.session_status(s["id"])
    assert status["activityCount"] == 2  # "artifact" + "satisfied", both posted by "a"
    assert status["satisfaction"] == {"a": True}
