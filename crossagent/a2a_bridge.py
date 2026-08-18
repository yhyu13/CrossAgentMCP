"""Per-agent stdio MCP bridge: peer A2A tools + pool coordination tools.

This is what Claude Code connects to via an agent's ``.mcp.json``. It exposes two
families of tools so a single headless ``claude -p`` turn can do everything the
turn contract demands (watch -> critique -> work -> report -> declare satisfied):

- **Peer A2A** (data plane) — ``a2a_peers`` / ``a2a_send`` / ``a2a_get_task`` /
  ``a2a_cancel_task`` / ``a2a_stream`` / ``a2a_peer_card``, plus ``a2a_inbox`` /
  ``a2a_respond`` against our own A2A server. Peers are addressed by ``agent_id``,
  resolved from a ``{agent_id -> url}`` map (multi-peer generalization of
  claude-a2a's single-peer bridge).
- **Pool** (control plane) — ``pool_register`` / ``pool_list_agents`` /
  ``session_*`` / ``activity_*`` / ``critique_*`` / ``resolve_critique`` /
  ``declare_satisfaction`` / ``session_status``. These hit the pool over HTTP
  via :class:`crossagent.pool_client.PoolClient`. Self-identity is bound at build
  time, so an agent cannot spoof another's activity/critique/satisfaction.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import suppress
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from crossagent.a2a import A2AClient
from crossagent.pool_client import PoolClient


def build_server(name: str, agent_id: str, peer_map: dict[str, str],
                 local_url: str, pool_url: str,
                 pool_token: str | None = None,
                 pool: PoolClient | None = None) -> Server:
    server: Server = Server(name)
    peers: dict[str, A2AClient] = {aid: A2AClient(url) for aid, url in peer_map.items()}
    local = A2AClient(local_url)
    if pool is None:
        pool = PoolClient(pool_url, token=pool_token)

    def _text(payload: Any) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]

    def _peer(args: dict[str, Any]) -> A2AClient:
        aid = args["peer"]
        if aid not in peers:
            raise ValueError(f"unknown peer '{aid}'; known: {sorted(peers)}")
        return peers[aid]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            # -- peer A2A --
            Tool(name="a2a_peers",
                 description="List the peer agents I can message (agent_id -> url).",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="a2a_peer_card",
                 description="Fetch a peer's A2A Agent Card.",
                 inputSchema={"type": "object",
                              "properties": {"peer": {"type": "string"}},
                              "required": ["peer"]}),
            Tool(name="a2a_send",
                 description="Send a text message to a peer; creates a Task on that peer.",
                 inputSchema={"type": "object",
                              "properties": {"peer": {"type": "string"},
                                             "text": {"type": "string"},
                                             "contextId": {"type": "string"}},
                              "required": ["peer", "text"]}),
            Tool(name="a2a_get_task",
                 description="Poll a task's state on a peer.",
                 inputSchema={"type": "object",
                              "properties": {"peer": {"type": "string"},
                                             "taskId": {"type": "string"}},
                              "required": ["peer", "taskId"]}),
            Tool(name="a2a_cancel_task",
                 description="Cancel a task on a peer.",
                 inputSchema={"type": "object",
                              "properties": {"peer": {"type": "string"},
                                             "taskId": {"type": "string"}},
                              "required": ["peer", "taskId"]}),
            Tool(name="a2a_stream",
                 description="Send a message to a peer and collect SSE updates until "
                             "final event or timeout.",
                 inputSchema={"type": "object",
                              "properties": {"peer": {"type": "string"},
                                             "text": {"type": "string"},
                                             "contextId": {"type": "string"},
                                             "timeoutSec": {"type": "number", "default": 30}},
                              "required": ["peer", "text"]}),
            Tool(name="a2a_inbox",
                 description="List tasks peers sent ME that await my reply.",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="a2a_respond",
                 description="Reply to an inbox task; marks it completed.",
                 inputSchema={"type": "object",
                              "properties": {"taskId": {"type": "string"},
                                             "text": {"type": "string"}},
                              "required": ["taskId", "text"]}),

            # -- pool: registry --
            Tool(name="pool_register",
                 description="Register myself in the pool with my Agent Card and url.",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="pool_list_agents",
                 description="List all agents currently registered in the pool.",
                 inputSchema={"type": "object", "properties": {}}),

            # -- pool: sessions --
            Tool(name="pool_list_sessions",
                 description="List all sessions in the pool.",
                 inputSchema={"type": "object", "properties": {}}),
            Tool(name="session_create",
                 description="Create a new session with a shared goal and optional members.",
                 inputSchema={"type": "object",
                              "properties": {"goal": {"type": "string"},
                                             "members": {"type": "array",
                                                         "items": {"type": "string"}}},
                              "required": ["goal"]}),
            Tool(name="session_join",
                 description="Join an existing session.",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"}},
                              "required": ["sessionId"]}),
            Tool(name="session_leave",
                 description="Leave a session.",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"}},
                              "required": ["sessionId"]}),
            Tool(name="session_get",
                 description="Get a session's full state.",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"}},
                              "required": ["sessionId"]}),
            Tool(name="session_status",
                 description="Get a session's status (per-agent satisfaction + allSatisfied).",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"}},
                              "required": ["sessionId"]}),

            # -- pool: activity (watching peers) --
            Tool(name="activity_post",
                 description="Post my own activity event (started/finished/artifact/...).",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"},
                                             "type": {"type": "string"},
                                             "payload": {"type": "object"}},
                              "required": ["sessionId", "type"]}),
            Tool(name="activity_since",
                 description="Watch peers: list activity events after a sequence number.",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"},
                                             "sinceSeq": {"type": "integer", "default": 0}},
                              "required": ["sessionId"]}),

            # -- pool: critique --
            Tool(name="critique_post",
                 description="Post a critique of a peer's work (opens a critique thread).",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"},
                                             "targetAgent": {"type": "string"},
                                             "text": {"type": "string"},
                                             "targetSeq": {"type": "integer"}},
                              "required": ["sessionId", "targetAgent", "text"]}),
            Tool(name="critique_list",
                 description="List critique threads in a session.",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"}},
                              "required": ["sessionId"]}),
            Tool(name="resolve_critique",
                 description="Resolve (close) a critique thread aimed at me, with my fix note.",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"},
                                             "critiqueId": {"type": "string"},
                                             "text": {"type": "string"}},
                              "required": ["sessionId", "critiqueId", "text"]}),

            # -- pool: goal --
            Tool(name="declare_satisfaction",
                 description="Declare whether I am satisfied with the shared goal.",
                 inputSchema={"type": "object",
                              "properties": {"sessionId": {"type": "string"},
                                             "satisfied": {"type": "boolean", "default": True},
                                             "summary": {"type": "string"}},
                              "required": ["sessionId"]}),
        ]

    @server.call_tool()
    async def call_tool(tool: str, args: dict[str, Any]) -> list[TextContent]:
        try:
            # -- peer A2A --
            if tool == "a2a_peers":
                return _text(peer_map)
            if tool == "a2a_peer_card":
                return _text(await _peer(args).get_card())
            if tool == "a2a_send":
                return _text(await _peer(args).send_message(args["text"], args.get("contextId")))
            if tool == "a2a_get_task":
                return _text(await _peer(args).get_task(args["taskId"]))
            if tool == "a2a_cancel_task":
                return _text(await _peer(args).cancel_task(args["taskId"]))
            if tool == "a2a_stream":
                events: list[dict[str, Any]] = []
                timeout = float(args.get("timeoutSec", 30))

                async def _collect() -> None:
                    async for ev in _peer(args).stream_message(args["text"], args.get("contextId")):
                        events.append(ev)
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(_collect(), timeout=timeout)
                return _text(events)
            if tool == "a2a_inbox":
                return _text(await local.inbox())
            if tool == "a2a_respond":
                return _text(await local.respond(args["taskId"], args["text"]))

            # -- pool: registry --
            if tool == "pool_register":
                card = {}
                with suppress(Exception):
                    card = await local.get_card()
                return _text(await pool.register(agent_id, card=card, url=local_url))
            if tool == "pool_list_agents":
                return _text(await pool.list_agents())

            # -- pool: sessions --
            if tool == "pool_list_sessions":
                return _text(await pool.session_list())
            if tool == "session_create":
                return _text(await pool.session_create(args["goal"], args.get("members")))
            if tool == "session_join":
                return _text(await pool.session_join(args["sessionId"], agent_id))
            if tool == "session_leave":
                return _text(await pool.session_leave(args["sessionId"], agent_id))
            if tool == "session_get":
                return _text(await pool.session_get(args["sessionId"]))
            if tool == "session_status":
                return _text(await pool.session_status(args["sessionId"]))

            # -- pool: activity --
            if tool == "activity_post":
                return _text(await pool.post_activity(args["sessionId"], agent_id,
                                                      args["type"], args.get("payload")))
            if tool == "activity_since":
                return _text(await pool.activity_since(args["sessionId"],
                                                       int(args.get("sinceSeq", 0))))

            # -- pool: critique --
            if tool == "critique_post":
                return _text(await pool.critique(args["sessionId"], agent_id,
                                                 args["targetAgent"], args["text"],
                                                 args.get("targetSeq")))
            if tool == "critique_list":
                return _text(await pool.list_critiques(args["sessionId"]))
            if tool == "resolve_critique":
                return _text(await pool.resolve_critique(args["sessionId"],
                                                         args["critiqueId"], agent_id,
                                                         args["text"]))

            # -- pool: goal --
            if tool == "declare_satisfaction":
                return _text(await pool.declare_satisfaction(
                    args["sessionId"], agent_id,
                    bool(args.get("satisfied", True)), args.get("summary")))
        except Exception as e:  # noqa: BLE001 - report any failure as structured text
            return _text({"error": str(e)})
        raise ValueError(f"unknown tool: {tool}")

    return server


async def _run(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    # CLI: a2a_bridge.py <name> <agent_id> <local_url> <pool_url> <peer_map_json> [pool_token]
    name = sys.argv[1]
    agent_id = sys.argv[2]
    local_url = sys.argv[3]
    pool_url = sys.argv[4]
    peer_map: dict[str, str] = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
    pool_token: str | None = (sys.argv[6] if len(sys.argv) > 6 and sys.argv[6]
                              else os.environ.get("CROSSAGENT_POOL_TOKEN"))
    asyncio.run(_run(build_server(name, agent_id, peer_map, local_url, pool_url,
                                  pool_token=pool_token)))


if __name__ == "__main__":
    main()
