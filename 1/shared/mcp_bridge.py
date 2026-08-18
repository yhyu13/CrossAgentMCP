"""MCP server bridging a Claude Code agent to the A2A pool + its local A2A server.

CLI: mcp_bridge.py <name> <self_id> <pool_url> <local_url>

Endpoints:
  - POOL : central coordinator (register, sessions, activity, critique, consensus)
  - LOCAL: the agent's own A2A server (inbox + respond on tasks others sent us)

Peer messaging (`agentpool_send_to`) resolves the target agent's URL from the pool
registry, then talks A2A P2P directly.

Tools exposed to the agent:
  agentpool_register, agentpool_list_agents,
  agentpool_send_to, agentpool_inbox, agentpool_respond,
  agentpool_session_create, agentpool_session_join, agentpool_session_leave,
  agentpool_session_status, agentpool_session_list, agentpool_set_goal,
  agentpool_post_activity, agentpool_watch, agentpool_critique, agentpool_resolve_critique,
  agentpool_declare_satisfaction
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import suppress
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from shared.a2a import A2AClient
from shared.pool_client import PoolClient


def build_server(name: str, self_id: str, pool_url: str, local_url: str) -> Server:
    server: Server = Server(name)
    pool = PoolClient(pool_url)
    local = A2AClient(local_url)
    peers: dict[str, A2AClient] = {}

    def _text(payload: Any) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]

    async def _peer(agent_id: str) -> A2AClient:
        if agent_id in peers:
            return peers[agent_id]
        for a in await pool.list_agents():
            if a["agentId"] == agent_id and a.get("url"):
                peers[agent_id] = A2AClient(a["url"])
                return peers[agent_id]
        raise RuntimeError(f"no registered url for agent {agent_id}")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name="agentpool_register",
                 description="Register self with the A2A pool (agent card + url).",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="agentpool_list_agents",
                 description="List all agents currently registered with the pool.",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="agentpool_send_to",
                 description="Send a text message directly to another agent (P2P A2A).",
                 inputSchema={
                     "type": "object",
                     "properties": {
                         "agentId": {"type": "string"},
                         "text": {"type": "string"},
                         "contextId": {"type": "string"},
                     },
                     "required": ["agentId", "text"],
                 }),
            Tool(name="agentpool_inbox",
                 description="List tasks on MY A2A server awaiting my reply.",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="agentpool_respond",
                 description="Reply to an inbox task on MY A2A server (marks completed).",
                 inputSchema={
                     "type": "object",
                     "properties": {"taskId": {"type": "string"},
                                    "text": {"type": "string"}},
                     "required": ["taskId", "text"],
                 }),
            Tool(name="agentpool_session_create",
                 description="Create a session and set its shared goal.",
                 inputSchema={
                     "type": "object",
                     "properties": {"goal": {"type": "string"}},
                     "required": ["goal"],
                 }),
            Tool(name="agentpool_session_join",
                 description="Bind self to an existing session.",
                 inputSchema={
                     "type": "object",
                     "properties": {"sessionId": {"type": "string"}},
                     "required": ["sessionId"],
                 }),
            Tool(name="agentpool_session_leave",
                 description="Leave a session (fails the session for the rest).",
                 inputSchema={
                     "type": "object",
                     "properties": {"sessionId": {"type": "string"}},
                     "required": ["sessionId"],
                 }),
            Tool(name="agentpool_session_status",
                 description="Get a session's state, members, satisfaction, critiques.",
                 inputSchema={
                     "type": "object",
                     "properties": {"sessionId": {"type": "string"}},
                     "required": ["sessionId"],
                 }),
            Tool(name="agentpool_session_list",
                 description="List all sessions on the pool.",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="agentpool_set_goal",
                 description="Set or update a session's shared goal.",
                 inputSchema={
                     "type": "object",
                     "properties": {"sessionId": {"type": "string"},
                                    "goal": {"type": "string"}},
                     "required": ["sessionId", "goal"],
                 }),
            Tool(name="agentpool_post_activity",
                 description=("Post an activity event to the session "
                              "(started/finished/self-improved/blocked)."),
                 inputSchema={
                     "type": "object",
                     "properties": {
                         "sessionId": {"type": "string"},
                         "type": {"type": "string"},
                         "text": {"type": "string"},
                         "targetAgentId": {"type": "string"},
                     },
                     "required": ["sessionId", "type"],
                 }),
            Tool(name="agentpool_watch",
                 description=("Watch a session's activity stream (SSE) and return "
                              "events since sinceSeq, until timeoutSec."),
                 inputSchema={
                     "type": "object",
                     "properties": {
                         "sessionId": {"type": "string"},
                         "sinceSeq": {"type": "integer", "default": 0},
                         "timeoutSec": {"type": "number", "default": 15},
                     },
                     "required": ["sessionId"],
                 }),
            Tool(name="agentpool_critique",
                 description="Send a critique of another agent's finished work.",
                 inputSchema={
                     "type": "object",
                     "properties": {
                         "sessionId": {"type": "string"},
                         "targetAgentId": {"type": "string"},
                         "text": {"type": "string"},
                     },
                     "required": ["sessionId", "targetAgentId", "text"],
                 }),
            Tool(name="agentpool_resolve_critique",
                 description="Resolve a critique against self after self-improving.",
                 inputSchema={
                     "type": "object",
                     "properties": {
                         "sessionId": {"type": "string"},
                         "critiqueId": {"type": "string"},
                         "text": {"type": "string"},
                     },
                     "required": ["sessionId", "critiqueId", "text"],
                 }),
            Tool(name="agentpool_declare_satisfaction",
                 description="Declare that self is satisfied with the shared goal.",
                 inputSchema={
                     "type": "object",
                     "properties": {"sessionId": {"type": "string"}},
                     "required": ["sessionId"],
                 }),
        ]

    @server.call_tool()
    async def call_tool(tool: str, args: dict[str, Any]) -> list[TextContent]:
        try:
            if tool == "agentpool_register":
                try:
                    card = await local.get_card()
                except Exception:  # noqa: BLE001
                    card = {"name": self_id, "description": self_id, "url": local_url}
                return _text(await pool.register(self_id, card, card.get("url", local_url)))
            if tool == "agentpool_list_agents":
                return _text(await pool.list_agents())
            if tool == "agentpool_send_to":
                peer = await _peer(args["agentId"])
                return _text(await peer.send_message(args["text"], args.get("contextId")))
            if tool == "agentpool_inbox":
                return _text(await local.inbox())
            if tool == "agentpool_respond":
                return _text(await local.respond(args["taskId"], args["text"]))
            if tool == "agentpool_session_create":
                return _text(await pool.create_session(args["goal"], creator=self_id))
            if tool == "agentpool_session_join":
                return _text(await pool.join_session(args["sessionId"], self_id))
            if tool == "agentpool_session_leave":
                return _text(await pool.leave_session(args["sessionId"], self_id))
            if tool == "agentpool_session_status":
                return _text(await pool.session_status(args["sessionId"]))
            if tool == "agentpool_session_list":
                return _text(await pool.list_sessions())
            if tool == "agentpool_set_goal":
                return _text(await pool.set_goal(args["sessionId"], args["goal"]))
            if tool == "agentpool_post_activity":
                return _text(await pool.post_activity(
                    args["sessionId"], self_id, args["type"],
                    text=args.get("text", ""), target=args.get("targetAgentId")))
            if tool == "agentpool_watch":
                events: list[dict[str, Any]] = []
                since = int(args.get("sinceSeq", 0))
                timeout = float(args.get("timeoutSec", 15))

                async def _collect() -> None:
                    async for ev in pool.activity_subscribe(args["sessionId"], since):
                        events.append(ev)
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(_collect(), timeout=timeout)
                return _text(events)
            if tool == "agentpool_critique":
                return _text(await pool.critique_send(
                    args["sessionId"], self_id, args["targetAgentId"], args["text"]))
            if tool == "agentpool_resolve_critique":
                return _text(await pool.critique_resolve(
                    args["sessionId"], args["critiqueId"], self_id, args["text"]))
            if tool == "agentpool_declare_satisfaction":
                return _text(await pool.declare_satisfaction(args["sessionId"], self_id))
        except Exception as e:  # noqa: BLE001
            return _text({"error": str(e)})
        raise ValueError(f"unknown tool: {tool}")

    return server


async def _run(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    # CLI: mcp_bridge.py <name> <self_id> <pool_url> <local_url>
    if len(sys.argv) != 5:
        raise SystemExit(
            f"usage: {sys.argv[0]} <name> <self_id> <pool_url> <local_url>")
    name, self_id, pool_url, local_url = sys.argv[1:5]
    asyncio.run(_run(build_server(name, self_id, pool_url, local_url)))


if __name__ == "__main__":
    main()
