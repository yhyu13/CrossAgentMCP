"""MCP bridge end-to-end tests over stdio (the real `.mcp.json` path).

Spawns `python -m shared.mcp_bridge` as a subprocess and drives it with the MCP
client, against a live pool. Verifies the tool surface a Claude Code session gets.
"""
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def _params(pool_url: str) -> StdioServerParameters:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "shared.mcp_bridge", "a", "a", pool_url,
              "http://127.0.0.1:9101"],
        env=env,
        cwd=str(ROOT),
    )


async def test_bridge_lists_tools_and_registers(live_client) -> None:
    pool, base = live_client
    async with stdio_client(_params(base)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "agentpool_register" in names
            assert "agentpool_list_agents" in names
            assert "agentpool_critique" in names

            await session.call_tool("agentpool_register", {})
            result = await session.call_tool("agentpool_list_agents", {})
            payload = json.loads(result.content[0].text)
            assert any(a["agentId"] == "a" for a in payload)


async def test_bridge_session_flow_over_stdio(live_client) -> None:
    pool, base = live_client
    await pool.register("b", {"name": "B"}, "http://127.0.0.1:9102")

    async with stdio_client(_params(base)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("agentpool_register", {})

            created = json.loads((await session.call_tool(
                "agentpool_session_create", {"goal": "g"})).content[0].text)
            sid = created["id"]

            await session.call_tool("agentpool_session_join", {"sessionId": sid})
            await pool.join_session(sid, "b")

            await session.call_tool("agentpool_post_activity",
                                    {"sessionId": sid, "type": "finished",
                                     "text": "DRAFT"})
            crit = json.loads((await session.call_tool(
                "agentpool_critique", {"sessionId": sid, "targetAgentId": "a",
                                 "text": "please fix"})).content[0].text)
            assert crit["targetAgentId"] == "a"

            await session.call_tool(
                "agentpool_resolve_critique",
                {"sessionId": sid, "critiqueId": crit["id"], "text": "fixed"})
            await session.call_tool("agentpool_declare_satisfaction",
                                    {"sessionId": sid})

    st = await pool.session_status(sid)
    assert st["satisfaction"]["a"] is True
